import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { OrganizationMembershipLevel } from 'lib/constants'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { AppContext, TeamType } from '~/types'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ticketPatternSettingsLogic } from './ticketPatternSettingsLogic'
import { TicketPatternsSection } from './TicketPatternsSection'

describe('TicketPatternsSection', () => {
    let logic: ReturnType<typeof ticketPatternSettingsLogic.build>

    const mountWithTicketAccess = (
        ticketAccess: AccessControlLevel,
        projectLevel: OrganizationMembershipLevel = OrganizationMembershipLevel.Admin
    ): void => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: projectLevel,
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

    it('does not claim a team has no topics when the list fails to load', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/pattern_overrides/': () => [500, {}],
                '/api/organizations/:organization_id/roles/': () => [200, { results: [] }],
            },
        })
        mountWithTicketAccess(AccessControlLevel.Editor)

        await waitFor(() => expect(screen.getByText(/Couldn't load your muted and watched topics/)).toBeInTheDocument())
        expect(screen.queryByText('None yet')).not.toBeInTheDocument()
    })

    it('turns the detection settings off for a project member who is not an admin', () => {
        mountWithTicketAccess(AccessControlLevel.Editor, OrganizationMembershipLevel.Member)

        expect(screen.getByTestId('ticket-pattern-detection-toggle')).toBeDisabled()
        // LemonSelect renders a button that stays focusable so the reason tooltip still opens.
        expect(screen.getByTestId('ticket-pattern-notify-role')).toHaveAttribute('aria-disabled', 'true')
    })

    it('turns the override controls off for someone who can only read tickets', () => {
        mountWithTicketAccess(AccessControlLevel.Viewer)

        expect(screen.getByTestId('ticket-pattern-override-mute-input')).toBeDisabled()
        // LemonButton keeps the element focusable so the reason tooltip still opens.
        expect(screen.getByTestId('ticket-pattern-override-mute-add')).toHaveAttribute('aria-disabled', 'true')
    })
})
