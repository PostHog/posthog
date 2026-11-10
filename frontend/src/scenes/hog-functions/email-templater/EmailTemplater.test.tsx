import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { NativeEmailIntegrationChoice } from './EmailTemplater'
import { SandboxSenderChoice, SandboxSenderChoiceContext } from './SandboxSenderChoiceContext'
import { EmailTemplateFrom } from './types'

let mockSenderRotationEnabled = false
let singleSelectProps: Record<string, any> = {}
let multipleSelectProps: Record<string, any> = {}

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: () => mockSenderRotationEnabled,
}))

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonInputSelect: (props: Record<string, any>) => {
        multipleSelectProps = props
        return <div data-attr="multiple-email-sender-select" />
    },
    LemonSelect: (props: Record<string, any>) => {
        singleSelectProps = props
        return <div data-attr="single-email-sender-select" />
    },
}))

const OWN_SENDERS = [
    { id: 1, kind: 'email', display_name: 'Alice <alice@example.com>' },
    { id: 2, kind: 'email', display_name: 'Bob <bob@example.com>' },
]

function mockSenders(integrations: Record<string, unknown>[]): void {
    jest.mocked(useValues).mockReturnValue({ integrationsLoading: false, integrations })
}

function renderChoice(sandbox: SandboxSenderChoice | null, value: EmailTemplateFrom = { integrationId: 1 }): jest.Mock {
    const onChange = jest.fn()
    render(
        <SandboxSenderChoiceContext.Provider value={sandbox}>
            <NativeEmailIntegrationChoice label="From" value={value} onChange={onChange} />
        </SandboxSenderChoiceContext.Provider>
    )
    return onChange
}

function singleSelectOptions(): { label: string; value: number }[] {
    return singleSelectProps.options.flatMap((group: { options: { label: string; value: number }[] }) => group.options)
}

function sandboxOptionValue(): number {
    const option = singleSelectOptions().find((candidate) => candidate.label === 'Sandbox sender')
    if (!option) {
        throw new Error('The picker offers no sandbox sender')
    }
    return option.value
}

describe('NativeEmailIntegrationChoice', () => {
    afterEach(cleanup)

    beforeEach(() => {
        mockSenderRotationEnabled = false
        singleSelectProps = {}
        multipleSelectProps = {}
        mockSenders(OWN_SENDERS)
    })

    it.each([
        [false, 'single-email-sender-select'],
        [true, 'multiple-email-sender-select'],
    ])('renders the expected sender picker when the rotation flag is %s', (flagEnabled, expectedPicker) => {
        mockSenderRotationEnabled = flagEnabled

        render(<NativeEmailIntegrationChoice label="From" value={{ integrationId: 1 }} onChange={jest.fn()} />)

        expect(screen.getByTestId(expectedPicker)).toBeInTheDocument()
        expect(screen.getByText('Custom sender')).toBeInTheDocument()
    })

    it('offers no sandbox sender when the step does not provide one', () => {
        renderChoice(null)

        expect(singleSelectOptions().map((option) => option.label)).not.toContain('Sandbox sender')
    })

    it('switches an own-sender step to the sandbox sender from the From picker', () => {
        const onSelect = jest.fn()
        const onChange = renderChoice({ selected: false, fromLine: null, onSelect })

        singleSelectProps.onChange(sandboxOptionValue())

        expect(onSelect).toHaveBeenCalled()
        expect(onChange).not.toHaveBeenCalled()
    })

    it('shows the sandbox sender as the choice of a sandbox step, without own-sender settings', () => {
        renderChoice({ selected: true, fromLine: 'Example via PostHog <sandbox@example.com>', onSelect: jest.fn() }, {})

        expect(singleSelectProps.value).toEqual(sandboxOptionValue())
        expect(screen.queryByText('Custom sender')).not.toBeInTheDocument()
        expect(screen.getByText(/Example via PostHog <sandbox@example.com>/)).toBeInTheDocument()
    })

    it('switches a sandbox step back to an own sender from the From picker', () => {
        const onChange = renderChoice({ selected: true, fromLine: null, onSelect: jest.fn() }, {})

        singleSelectProps.onChange(2)

        expect(onChange).toHaveBeenCalledWith({ integrationId: 2, integrationIds: undefined })
    })

    it('offers the sandbox sender to a project with no own senders yet', () => {
        mockSenders([])

        renderChoice({ selected: false, fromLine: null, onSelect: jest.fn() }, {})

        expect(screen.queryByText('No email senders configured yet')).not.toBeInTheDocument()
        expect(singleSelectOptions().map((option) => option.label)).toContain('Sandbox sender')
    })

    it('switches to the sandbox sender from the multiple-sender picker', () => {
        mockSenderRotationEnabled = true
        const onSelect = jest.fn()
        const onChange = renderChoice({ selected: false, fromLine: null, onSelect })
        const sandboxOption = multipleSelectProps.options.find(
            (option: { label: string }) => option.label === 'Sandbox sender'
        )

        multipleSelectProps.onChange([1, sandboxOption.value])

        expect(onSelect).toHaveBeenCalled()
        expect(onChange).not.toHaveBeenCalled()
    })
})
