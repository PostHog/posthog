import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import posthog from 'posthog-js'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { initKeaTests } from '~/test/init'
import { ExperimentStatus, SDKKey } from '~/types'
import type { Experiment } from '~/types'

import { ExperimentImplementationDetails, type ImplementationSnippetPlacement } from './ExperimentImplementationDetails'

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn(),
}))

const PROMPT_EXPERIMENT = {
    id: 11,
    status: ExperimentStatus.Draft,
    feature_flag: { key: 'my-prompt-experiment' },
    parameters: {
        prompt_metadata: { name: 'support-reply', templates: ['support-reply'], versions: [1, 2] },
    },
} as unknown as Experiment

const experimentWithStatus = (status: ExperimentStatus): Experiment =>
    ({
        id: 42,
        status,
        feature_flag: {
            key: 'new-checkout',
            filters: {
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'one-page', rollout_percentage: 50 },
                    ],
                },
            },
        },
    }) as unknown as Experiment

const clickCopy = async (container: HTMLElement, index = 0): Promise<void> => {
    fireEvent.click(container.querySelectorAll('[data-attr="copy-code-button"]')[index])
    // copyToClipboard resolves before onCopy runs, so let the promise settle.
    await act(async () => {})
}

describe('ExperimentImplementationDetails', () => {
    let captureSpy: jest.SpyInstance

    // Other code on the page captures too, so pick out this event's properties.
    const capturedProperties = (eventName: string): unknown[] =>
        captureSpy.mock.calls.filter(([event]) => event === eventName).map(([, properties]) => properties)
    const snippetCopies = (): unknown[] => capturedProperties('experiment implementation snippet copied')
    const agentPromptCopies = (): unknown[] => capturedProperties('experiment implementation agent prompt copied')

    beforeEach(() => {
        // The syntax highlighter reads the theme from kea.
        initKeaTests()
        jest.mocked(copyToClipboard).mockResolvedValue(true)
        captureSpy = jest.spyOn(posthog, 'capture').mockReturnValue(undefined as any)
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    // The agent prompt runs past 50 lines. Without the collapse it pushes the rest of the page
    // out of view, so the snippet must open collapsed and only unfold when the user asks.
    it('collapses the agent prompt until expanded', () => {
        render(<ExperimentImplementationDetails experiment={PROMPT_EXPERIMENT} placement="draft_header" />)

        expect(screen.queryByText(/Reference docs/)).not.toBeInTheDocument()

        fireEvent.click(screen.getByText(/more lines/))

        expect(screen.getByText(/Reference docs/)).toBeInTheDocument()
    })

    // Autocapture can't tell this snippet apart from other copy buttons on the page, or say where
    // it sat. The event answers whether people still copy the snippet once an agent wrote the code.
    it.each([
        ['draft_header', ExperimentStatus.Draft],
        ['code_tab', ExperimentStatus.Running],
    ] as [ImplementationSnippetPlacement, ExperimentStatus][])(
        'captures a copy of the code snippet from the %s',
        async (placement, status) => {
            const { container } = render(
                <ExperimentImplementationDetails experiment={experimentWithStatus(status)} placement={placement} />
            )

            await clickCopy(container)

            expect(snippetCopies()).toEqual([
                {
                    experiment_id: 42,
                    experiment_status: status,
                    placement,
                    sdk: SDKKey.JS_WEB,
                    variant: 'one-page',
                    snippet_kind: 'code',
                },
            ])
        }
    )

    it('reports the SDK and variant picked in the selects', async () => {
        const { container } = render(
            <ExperimentImplementationDetails
                experiment={experimentWithStatus(ExperimentStatus.Running)}
                placement="code_tab"
            />
        )

        // Each select opens its options in a popover outside the container.
        fireEvent.click(within(container).getByText('JavaScript'))
        fireEvent.click(await screen.findByText('Python'))
        fireEvent.click(within(container).getByText('one-page'))
        fireEvent.click(await screen.findByText('control'))
        await clickCopy(container)

        expect(snippetCopies()).toEqual([expect.objectContaining({ sdk: SDKKey.PYTHON, variant: 'control' })])
    })

    // The override line tests the flag in the user's own browser. Counting it as an implementation
    // copy would overstate how many people added the flag to their code.
    it('captures a copy of the "Test that it works" snippet as a test override', async () => {
        const { container } = render(
            <ExperimentImplementationDetails
                experiment={experimentWithStatus(ExperimentStatus.Draft)}
                placement="draft_header"
            />
        )

        await clickCopy(container, 1)

        expect(snippetCopies()).toEqual([
            expect.objectContaining({ sdk: SDKKey.JS_WEB, variant: 'one-page', snippet_kind: 'test_override' }),
        ])
    })

    it('captures a copy of the agent prompt for a prompt experiment on its own event', async () => {
        const { container } = render(
            <ExperimentImplementationDetails experiment={PROMPT_EXPERIMENT} placement="draft_header" />
        )

        await clickCopy(container)

        expect(agentPromptCopies()).toEqual([
            {
                experiment_id: 11,
                experiment_status: ExperimentStatus.Draft,
                placement: 'draft_header',
                prompt_kind: 'prompt_experiment',
                source: 'prompt_text',
            },
        ])
        expect(snippetCopies()).toEqual([])
    })
})
