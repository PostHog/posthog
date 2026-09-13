import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { AppContext, TeamType } from '~/types'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ticketPatternSettingsLogic } from './ticketPatternSettingsLogic'
import { TicketPatternsSection } from './TicketPatternsSection'

describe('TicketPatternsSection', () => {
    let logic: ReturnType<typeof ticketPatternSettingsLogic.build>

    const mountWithTicketAccess = (ticketAccess: AccessControlLevel): void => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            conversations_settings: { pattern_detection_enabled: true },
        } as TeamType)
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: { [AccessControlResourceType.Ticket]: ticketAccess },
        } as AppContext
        logic = ticketPatternSettingsLogic()
        logic.mount()
        render(
            <Provider>
                <TicketPatternsSection />
            </Provider>
        )
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/pattern_overrides/': () => [
                    200,
                    { results: [], count: 0, next: null, previous: null },
                ],
                '/api/organizations/:organization_id/roles/': () => [200, { results: [] }],
            },
            post: {
                '/api/projects/:team_id/conversations/pattern_overrides/': () => [
                    400,
                    { detail: 'An override for this topic already exists.' },
                ],
            },
        })
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    it('keeps the typed topic when the server rejects the override', async () => {
        mountWithTicketAccess(AccessControlLevel.Editor)

        const input = screen.getByTestId('ticket-pattern-override-mute-input')
        await userEvent.type(input, 'weekly digest')
        await userEvent.click(screen.getByTestId('ticket-pattern-override-mute-add'))

        await waitFor(() => expect(input).toHaveValue('weekly digest'))
    })

    it('turns the override controls off for someone who can only read tickets', () => {
        mountWithTicketAccess(AccessControlLevel.Viewer)

        expect(screen.getByTestId('ticket-pattern-override-mute-input')).toBeDisabled()
        // LemonButton keeps the element focusable so the reason tooltip still opens.
        expect(screen.getByTestId('ticket-pattern-override-mute-add')).toHaveAttribute('aria-disabled', 'true')
    })
})
