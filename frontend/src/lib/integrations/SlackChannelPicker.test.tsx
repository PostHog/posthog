import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { SlackChannelPicker } from './SlackIntegrationHelpers'

const INTEGRATION: IntegrationType = {
    id: 1,
    kind: 'slack',
    display_name: 'Fake Workspace',
    icon_url: '',
    config: {},
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
}

const CHANNELS = [
    {
        id: 'C0B6HUH9FUH',
        name: 'test-slack-notifications',
        is_private: false,
        is_member: true,
        is_ext_shared: false,
        is_private_without_access: false,
    },
    {
        id: 'C111111111',
        name: 'general',
        is_private: false,
        is_member: true,
        is_ext_shared: false,
        is_private_without_access: false,
    },
]

describe('SlackChannelPicker', () => {
    let channelsRequestSearchQueries: (string | null)[] = []

    beforeEach(() => {
        channelsRequestSearchQueries = []
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/channels': (req: any) => {
                    const search = req.url.searchParams.get('search')
                    const channelId = req.url.searchParams.get('channel_id')
                    if (channelId) {
                        const match = CHANNELS.find((c) => c.id === channelId)
                        return [200, { channels: match ? [match] : [] }]
                    }
                    channelsRequestSearchQueries.push(search)
                    // Server-side search: substring match in name or id (mirrors the backend).
                    const filtered = search
                        ? CHANNELS.filter(
                              (c) =>
                                  c.name.toLowerCase().includes(search.toLowerCase()) ||
                                  c.id.toLowerCase().includes(search.toLowerCase())
                          )
                        : CHANNELS
                    return [
                        200,
                        {
                            channels: filtered,
                            lastRefreshedAt: '2026-01-01T00:00:00Z',
                            has_more: false,
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('does not search for the composite key when the input is focused with an existing value', async () => {
        // The saved value is the composite "id|#name" — what the picker stores after a user selection.
        const { container } = render(
            <Provider>
                <SlackChannelPicker
                    integration={INTEGRATION}
                    value="C0B6HUH9FUH|#test-slack-notifications"
                    onChange={jest.fn()}
                />
            </Provider>
        )

        // Initial useEffect-driven load — single GET /channels with empty search.
        await waitFor(() => {
            expect(channelsRequestSearchQueries).toEqual([''])
        })

        // Focus the picker. LemonInputSelect._onFocus auto-fills the input with the selected
        // option's composite key, which lands in onInputChange. Before the fix this would have
        // triggered a second GET /channels?search=C0B6HUH9FUH|#test-slack-notifications, returning
        // zero matches and wiping the cached channel list. After the fix, no extra request fires
        // because the val equals the currently displayed key.
        const input = container.querySelector<HTMLInputElement>('input[data-attr="select-slack-channel"]')!
        await userEvent.click(input)

        // Give kea-loaders' debounce (300ms breakpoint on non-empty search) a chance to fire if
        // the guard were missing — still expect only the initial empty-search call.
        await new Promise((resolve) => setTimeout(resolve, 400))
        expect(channelsRequestSearchQueries).toEqual([''])
    })

    it('still searches when the user actually types a different value', async () => {
        // Render without an initial value so the input starts empty and typing isn't appended
        // to LemonInputSelect's auto-fill of an existing selection.
        const { container } = render(
            <Provider>
                <SlackChannelPicker integration={INTEGRATION} onChange={jest.fn()} />
            </Provider>
        )
        await waitFor(() => {
            expect(channelsRequestSearchQueries).toEqual([''])
        })

        const input = container.querySelector<HTMLInputElement>('input[data-attr="select-slack-channel"]')!
        await userEvent.click(input)
        await userEvent.type(input, 'general')

        // The typed text differs from any currently displayed key, so the server-side search fires.
        await waitFor(
            () => {
                expect(channelsRequestSearchQueries).toContain('general')
            },
            { timeout: 1500 }
        )
    })
})
