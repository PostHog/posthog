import { cleanup, fireEvent, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { InstrumentationCheckStatusEnumApi } from '../../../generated/api.schemas'
import { CHECKLIST_ALL_OK, CHECKLIST_PENDING, CHECKLIST_WARNING } from '../homeFixtures'
import { InstrumentationRow, InstrumentationRowProps } from './InstrumentationRow'

function renderRow(props: Partial<InstrumentationRowProps> = {}): ReturnType<typeof render> {
    return render(
        <InstrumentationRow
            checklist={CHECKLIST_WARNING}
            loading={false}
            pendingCheckKey={null}
            refreshing={false}
            refreshFailed={false}
            onDismiss={jest.fn()}
            onRestore={jest.fn()}
            onRefresh={jest.fn()}
            {...props}
        />
    )
}

describe('InstrumentationRow', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    it('shows the passing count the server reports', () => {
        const { container } = renderRow({ checklist: { ...CHECKLIST_PENDING, passing: 1, total: 7 } })

        expect(container.querySelector('[data-attr="home-instrumentation-toggle"]')?.textContent).toContain(
            'Instrumentation 1 of 7'
        )
    })

    it('starts closed when nothing warns and opens on toggle', () => {
        const { container } = renderRow({ checklist: CHECKLIST_PENDING })
        expect(container.textContent).not.toContain('Not enough generations to grade yet.')

        fireEvent.click(container.querySelector('[data-attr="home-instrumentation-toggle"]') as HTMLElement)

        expect(container.textContent).toContain('Not enough generations to grade yet.')
    })

    it('starts open when a check warns, with dismiss and recheck per check', () => {
        const onDismiss = jest.fn()
        const onRestore = jest.fn()
        const { container } = renderRow({ onDismiss, onRestore })

        expect(container.textContent).toContain('No generations carry a session id.')
        fireEvent.click(
            container.querySelector('[data-attr="ai-observability-instrumentation-checklist-dismiss"]') as HTMLElement
        )
        fireEvent.click(
            container.querySelector('[data-attr="ai-observability-instrumentation-checklist-recheck"]') as HTMLElement
        )

        expect(onDismiss).toHaveBeenCalledWith('sessions')
        expect(onRestore).toHaveBeenCalledWith('user_identity')
    })

    it('shows the agent prompt button only when there is a prompt', () => {
        const withPrompt = renderRow()
        expect(withPrompt.container.querySelector('[data-attr="home-instrumentation-prompt"]')).not.toBeNull()
        cleanup()

        const withoutPrompt = renderRow({ checklist: { ...CHECKLIST_WARNING, agent_prompt: null } })
        expect(withoutPrompt.container.querySelector('[data-attr="home-instrumentation-prompt"]')).toBeNull()
    })

    it('stays with Restore reachable when every check is ok or dismissed', () => {
        const onRestore = jest.fn()
        const [first, ...rest] = CHECKLIST_ALL_OK.checks
        const { container } = renderRow({
            checklist: {
                ...CHECKLIST_ALL_OK,
                checks: [{ ...first, status: InstrumentationCheckStatusEnumApi.Dismissed }, ...rest],
            },
            onRestore,
        })

        fireEvent.click(container.querySelector('[data-attr="home-instrumentation-toggle"]') as HTMLElement)
        fireEvent.click(
            container.querySelector('[data-attr="ai-observability-instrumentation-checklist-recheck"]') as HTMLElement
        )

        expect(onRestore).toHaveBeenCalledWith(first.key)
    })

    it('offers a retry beside the prompt when a refresh fails', () => {
        const onRefresh = jest.fn()
        const { container } = renderRow({ refreshFailed: true, onRefresh })
        const refresh = container.querySelector('[data-attr="home-instrumentation-refresh"]') as HTMLElement

        expect(container.textContent).toContain('Could not refresh the checklist.')
        expect(refresh.textContent).toBe('Try again')
        fireEvent.click(refresh)

        expect(onRefresh).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['loading ends without a checklist', null],
        ['every check passes', CHECKLIST_ALL_OK],
    ])('renders nothing once %s', (_name, checklist) => {
        const { container } = renderRow({ checklist })

        expect(container.querySelector('[data-attr="home-instrumentation"]')).toBeNull()
    })
})
