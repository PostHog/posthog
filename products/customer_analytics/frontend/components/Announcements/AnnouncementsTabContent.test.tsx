import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { announcementsLogic } from './announcementsLogic'
import { AnnouncementsTabContent } from './AnnouncementsTabContent'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))

describe('AnnouncementsTabContent', () => {
    let logic: ReturnType<typeof announcementsLogic.build>
    let postedBodies: any[]

    beforeEach(() => {
        postedBodies = []
        useMocks({
            get: {
                '/api/projects/:team_id/announcements/': { results: [], count: 0 },
                '/api/projects/:team_id/announcements/channels/': [
                    { id: 'C1', name: 'acme', is_member: true, customer_name: 'Acme' },
                    { id: 'C2', name: 'globex', is_member: true, customer_name: 'Globex' },
                ],
            },
            post: {
                '/api/projects/:team_id/announcements/': async ({ request }) => {
                    postedBodies.push(await request.json())
                    return [200, { results: [], count: 0 }]
                },
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_settings: { slack_enabled: true } })
        logic = announcementsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    function renderComposer(): void {
        logic.actions.setMessage('Offsite this week')
        logic.actions.setSelectedChannelIds(['C1', 'C2'])
        render(
            <Provider>
                <AnnouncementsTabContent />
            </Provider>
        )
    }

    function clickSend(): void {
        fireEvent.click(document.querySelector('[data-attr="send-announcement"]')!)
    }

    // Sending posts to customer channels and can't be undone, so the send button must
    // never reach the API on its own — it has to go through the confirmation first.
    it('asks for confirmation instead of sending, showing the channel count and message', async () => {
        renderComposer()

        clickSend()

        await waitFor(() => expect(screen.getByText('Send this announcement to 2 channels?')).toBeInTheDocument())
        expect(screen.getByText('Acme (#acme)')).toBeInTheDocument()
        expect(screen.getByText('Globex (#globex)')).toBeInTheDocument()
        expect(screen.getAllByText('Offsite this week').length).toBeGreaterThan(0)
        expect(postedBodies).toEqual([])
    })

    it('sends once the confirmation is accepted', async () => {
        renderComposer()

        clickSend()
        await waitFor(() => expect(document.querySelector('[data-attr="confirm-send-announcement"]')).not.toBeNull())
        fireEvent.click(document.querySelector('[data-attr="confirm-send-announcement"]')!)

        await waitFor(() => expect(postedBodies).toEqual([{ message: 'Offsite this week', channels: ['C1', 'C2'] }]))
    })
})
