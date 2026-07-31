import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ConversationsDisabledBanner } from './ConversationsDisabledBanner'

describe('ConversationsDisabledBanner', () => {
    let lastCapturedPayload: any = null

    beforeEach(() => {
        lastCapturedPayload = null
        useMocks({
            patch: {
                '/api/environments/:id': async ({ request }) => {
                    lastCapturedPayload = await request.json()
                    return [200, { ...MOCK_DEFAULT_TEAM, ...lastCapturedPayload }]
                },
            },
        })
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, conversations_enabled: false })
    })

    afterEach(() => {
        teamLogic.unmount()
        cleanup()
    })

    // Regression: the "Enable" button used to be a plain link to the settings page and never
    // flipped conversations_enabled itself, so clicking it left the banner (and the user) stuck.
    it('flips conversations_enabled when Enable is clicked', async () => {
        render(
            <Provider>
                <ConversationsDisabledBanner />
            </Provider>
        )

        await userEvent.click(screen.getByText('Enable'))

        expect(lastCapturedPayload).toEqual({ conversations_enabled: true })
    })

    // Regression: the button carried `hidden @md:flex`, so it never rendered below @md
    // container width, leaving only the "Learn more" link visible.
    it('does not hide the Enable button at any container width', () => {
        render(
            <Provider>
                <ConversationsDisabledBanner />
            </Provider>
        )

        const button = screen.getByText('Enable').closest('button')
        expect(button).not.toBeNull()
        expect(button!.className).not.toMatch(/\bhidden\b/)
    })
})
