import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { ticketPatternSettingsLogic } from './ticketPatternSettingsLogic'
import { TicketPatternsSection } from './TicketPatternsSection'

describe('TicketPatternsSection', () => {
    let logic: ReturnType<typeof ticketPatternSettingsLogic.build>

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
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            conversations_settings: { pattern_detection_enabled: true },
        } as TeamType)
        logic = ticketPatternSettingsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    it('keeps the typed topic when the server rejects the override', async () => {
        render(
            <Provider>
                <TicketPatternsSection />
            </Provider>
        )

        const input = screen.getByTestId('ticket-pattern-override-mute-input')
        await userEvent.type(input, 'weekly digest')
        await userEvent.click(screen.getByTestId('ticket-pattern-override-mute-add'))

        await waitFor(() => expect(input).toHaveValue('weekly digest'))
    })
})
