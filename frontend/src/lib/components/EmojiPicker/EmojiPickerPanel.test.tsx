import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import emojibaseData from 'emojibase-data/en/data.json'
import emojibaseMessages from 'emojibase-data/en/messages.json'

import { projectLogic } from 'scenes/projectLogic'

import { emojiSearchSuggestCreate } from '~/generated/core/api'
import { initKeaTests } from '~/test/init'

import { EmojiPickerPanel } from './EmojiPickerPanel'

jest.mock('~/generated/core/api', () => ({ emojiSearchSuggestCreate: jest.fn() }))

// The two files the build copies to /static/emoji. Any other URL, such as the frimousse CDN default,
// has no same-origin copy and the app's connect-src refuses it, so the mock refuses it too.
const SERVED: Record<string, unknown> = {
    '/static/emoji/en/data.json': emojibaseData,
    '/static/emoji/en/messages.json': emojibaseMessages,
}

describe('EmojiPickerPanel', () => {
    const originalFetch = globalThis.fetch
    let fetchMock: jest.Mock

    beforeEach(() => {
        initKeaTests()
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 1, name: 'Test project' } as any)
        jest.mocked(emojiSearchSuggestCreate).mockReset()
        // frimousse caches the data in localStorage and skips the fetch on a hit.
        localStorage.clear()
        sessionStorage.clear()
        fetchMock = jest.fn(async (url: string) => {
            if (!(url in SERVED)) {
                throw new TypeError(`Failed to fetch ${url}`)
            }
            return { json: async () => SERVED[url], headers: { get: () => null } }
        })
        globalThis.fetch = fetchMock as unknown as typeof fetch
    })

    afterEach(() => {
        cleanup()
        globalThis.fetch = originalFetch
    })

    it('renders emojis from the same-origin files the build serves', async () => {
        const { container } = render(<EmojiPickerPanel onEmojiSelect={jest.fn()} />)

        await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
        expect(fetchMock.mock.calls.map(([url]) => url).sort()).toEqual([
            '/static/emoji/en/data.json',
            '/static/emoji/en/messages.json',
        ])
        // frimousse also renders a hidden sizer row with the same button; real rows carry role="row".
        await waitFor(() =>
            expect(container.querySelector('[role="row"] [data-attr="emoji-picker-button"]')).toBeInTheDocument()
        )
    })

    it('offers related emojis when the normal search has no result', async () => {
        jest.mocked(emojiSearchSuggestCreate).mockResolvedValue({
            suggestions: [{ emoji: '🦖', label: 'T-Rex' }],
        })
        const onEmojiSelect = jest.fn()
        render(<EmojiPickerPanel initialSearch="jurassic park" onEmojiSelect={onEmojiSelect} />)

        await waitFor(() =>
            expect(emojiSearchSuggestCreate).toHaveBeenCalledWith(
                '1',
                { query: 'jurassic park' },
                { signal: expect.any(AbortSignal) }
            )
        )
        screen.getByLabelText('T-Rex').click()
        expect(onEmojiSelect).toHaveBeenCalledWith('🦖')
    })
})
