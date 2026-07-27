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

// A channel whose ID is not returned by the bulk /channels endpoint — simulating a workspace
// where the saved channel falls beyond the first page that the backend returns.
const OFF_PAGE_CHANNEL = {
    id: 'COFFPAGE9XX',
    name: 'off-page-channel',
    is_private: false,
    is_member: true,
    is_ext_shared: false,
    is_private_without_access: false,
}

describe('SlackChannelPicker', () => {
    let channelsRequestSearchQueries: (string | null)[] = []
    let channelIdLookups: string[] = []

    beforeEach(() => {
        channelsRequestSearchQueries = []
        channelIdLookups = []
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/channels': ({ request }) => {
                    const url = new URL(request.url)
                    const search = url.searchParams.get('search')
                    const channelId = url.searchParams.get('channel_id')
                    if (channelId) {
                        channelIdLookups.push(channelId)
                        const match =
                            CHANNELS.find((c) => c.id === channelId) ??
                            (OFF_PAGE_CHANNEL.id === channelId ? OFF_PAGE_CHANNEL : null)
                        return [200, { channels: match ? [match] : [] }]
                    }
                    channelsRequestSearchQueries.push(search)
                    // Server-side search: substring match in name or id (mirrors the backend).
                    // The bulk endpoint deliberately never returns OFF_PAGE_CHANNEL so we can
                    // verify name resolution falls back to the direct-by-id lookup.
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

        // Give kea-loaders' debounce (300ms breakpoint on non-empty search) plus the fetch round-trip
        // a generous buffer to fire if the guard were missing. We deliberately wait well past the
        // breakpoint window so a slow CI runner can't produce a false negative by observing
        // `['']` before the unwanted request lands.
        await new Promise((resolve) => setTimeout(resolve, 1000))
        expect(channelsRequestSearchQueries).toEqual([''])
    })

    // The saved channel needs to be in slackChannels for LemonInputSelect's options to contain a
    // matching key — otherwise the picker falls back to displaying the raw value text instead of
    // "#name (id)". The by-id fetch is what feeds the channel into slackChannels regardless of
    // bulk-list position, so it has to fire for both shapes the value can take. The lookup must
    // also use just the id portion: sending the composite would 404 against Slack's
    // conversations.info.
    it.each<[string, string]>([
        ['bare ID', 'COFFPAGE9XX'],
        ['composite "id|#name"', 'COFFPAGE9XX|#off-page-channel'],
    ])('directly fetches the saved channel by id on mount when value is a %s', async (_label, savedValue) => {
        render(
            <Provider>
                <SlackChannelPicker integration={INTEGRATION} value={savedValue} onChange={jest.fn()} />
            </Provider>
        )

        // loadSlackChannelById has a 500ms breakpoint before fetching, so wait generously.
        await waitFor(
            () => {
                expect(channelIdLookups).toContain('COFFPAGE9XX')
            },
            { timeout: 2000 }
        )
        // Never forward the composite to /channels?channel_id=… — that would 404 against Slack.
        expect(channelIdLookups).not.toContain('COFFPAGE9XX|#off-page-channel')
    })

    it('does not fire a direct lookup when there is no saved value', async () => {
        render(
            <Provider>
                <SlackChannelPicker integration={INTEGRATION} onChange={jest.fn()} />
            </Provider>
        )

        // Wait for the bulk load to finish so the test isn't racing the mount effects.
        await waitFor(() => {
            expect(channelsRequestSearchQueries).toEqual([''])
        })
        // Wait past the by-id breakpoint window so a stray call would have surfaced by now.
        await new Promise((resolve) => setTimeout(resolve, 800))
        expect(channelIdLookups).toEqual([])
    })

    it('does not reload the bulk list on blur when no search has clobbered the cache', async () => {
        // LemonInputSelect calls setInputValue('') on blur (LemonInputSelect.tsx:_onBlur), which
        // lands in onInputChange(''). Without the hasActiveSearchRef guard the empty-val branch
        // would unconditionally fire loadAllSlackChannels() and briefly toggle
        // allSlackChannelsLoading true → false, flickering the "Only the first page" hint off and
        // back on for every focus → blur cycle.
        const { container } = render(
            <Provider>
                <SlackChannelPicker
                    integration={INTEGRATION}
                    value="C0B6HUH9FUH|#test-slack-notifications"
                    onChange={jest.fn()}
                />
            </Provider>
        )

        // Wait for the initial useEffect-driven bulk load.
        await waitFor(() => {
            expect(channelsRequestSearchQueries).toEqual([''])
        })

        // Focus and blur the picker without typing — the user clicks into the input and then
        // clicks somewhere else. Clicking outside triggers LemonDropdown's onClickOutside, which
        // clears popoverFocusRef and blurs the input, so _onBlur reaches setInputValue('').
        const input = container.querySelector<HTMLInputElement>('input[data-attr="select-slack-channel"]')!
        await userEvent.click(input)
        await userEvent.click(document.body)

        // The empty-search load has no breakpoint, so a missed guard fires its request during the
        // awaited click above — verified by reverting the guard. 100ms is margin for CI scheduling.
        await new Promise((resolve) => setTimeout(resolve, 100))
        expect(channelsRequestSearchQueries).toEqual([''])
    })

    it('does reload the bulk list on blur after a search clobbered it', async () => {
        // Sanity check that the guard still allows the original "user typed a search, cleared
        // it, wants the full list back" recovery — otherwise the dropdown would stay stuck on
        // search results after the user gave up.
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
        await waitFor(() => expect(channelsRequestSearchQueries).toContain('general'), { timeout: 5000 })

        // Now clear the input — should trigger the recovery reload (empty search) to refresh the
        // bulk list back to the full first page.
        await userEvent.clear(input)
        await waitFor(
            () => {
                // The recovery is observable as a second empty-search request beyond the initial one.
                expect(channelsRequestSearchQueries.filter((q) => q === '').length).toBeGreaterThanOrEqual(2)
            },
            { timeout: 2000 }
        )
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
        // Timeout is generous: userEvent.type sims each keystroke, intermediate calls are cancelled
        // by the breakpoint, and the final search waits 300ms before fetching — well within 5s.
        await waitFor(
            () => {
                expect(channelsRequestSearchQueries).toContain('general')
            },
            { timeout: 5000 }
        )
    })
})
