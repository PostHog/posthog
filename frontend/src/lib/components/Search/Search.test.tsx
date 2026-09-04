import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Search } from './Search'
import { SearchItem } from './searchLogic'

// Base UI's ScrollArea reads layout that jsdom does not implement, and throws on the second
// render. The wrapper only scrolls, so the results render without it.
jest.mock('../ScrollableShadows/ScrollableShadows', () => ({
    ScrollableShadows: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

// jsdom has no PointerEvent, and the pointer sequence is what activates a result.
if (typeof window.PointerEvent === 'undefined') {
    window.PointerEvent = class extends MouseEvent {
        readonly pointerId: number
        constructor(type: string, init: PointerEventInit = {}) {
            super(type, init)
            this.pointerId = init.pointerId ?? 0
        }
    } as unknown as typeof window.PointerEvent
}

const INBOX: SearchItem = { id: 'inbox', name: 'Inbox', category: 'suggested', href: '/inbox' }
const SETTINGS: SearchItem = { id: 'settings', name: 'MCP settings', category: 'suggested', href: '/settings/mcp' }

describe('Search', () => {
    let onItemSelect: jest.Mock

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/search/': { results: [], counts: {} },
                '/api/projects/:team_id/file_system/': { results: [], count: 0 },
                '/api/projects/:team_id/conversations/tickets/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        onItemSelect = jest.fn()
    })

    // Let the search loaders settle before the environment is torn down, so a late
    // resolution cannot update an unmounted tree.
    afterEach(async () => {
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
        cleanup()
    })

    function renderResults(items: SearchItem[]): { rerenderWith: (next: SearchItem[]) => void } {
        const results = (list: SearchItem[]): JSX.Element => (
            <Search.Root logicKey="test" suggestedItems={list} onItemSelect={onItemSelect}>
                <Search.Results />
            </Search.Root>
        )
        const { rerender } = render(results(items))
        return { rerenderWith: (next) => rerender(results(next)) }
    }

    it('selects the pressed result even when the list reorders before the release', () => {
        const { rerenderWith } = renderResults([INBOX, SETTINGS])

        fireEvent.pointerDown(screen.getByText('Inbox'), { button: 0, pointerId: 1, clientX: 10, clientY: 10 })
        // A server category resolves and pushes the pressed item away from the cursor, so the
        // browser fires no click on it.
        rerenderWith([SETTINGS, INBOX])
        fireEvent.pointerUp(document.body, { pointerId: 1, clientX: 10, clientY: 10 })

        expect(onItemSelect).toHaveBeenCalledTimes(1)
        expect(onItemSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'inbox' }), false)
    })

    it('selects an undisturbed result once, not twice', () => {
        renderResults([INBOX, SETTINGS])
        const row = screen.getByText('Inbox')

        fireEvent.pointerDown(row, { button: 0, pointerId: 1, clientX: 10, clientY: 10 })
        fireEvent.pointerUp(row, { pointerId: 1, clientX: 10, clientY: 10 })
        // `detail` is the click count, which every click a pointer makes carries.
        fireEvent.click(row, { clientX: 10, clientY: 10, detail: 1 })

        expect(onItemSelect).toHaveBeenCalledTimes(1)
    })

    it('selects on Enter after the list move swallowed the click', () => {
        const { rerenderWith } = renderResults([INBOX, SETTINGS])

        fireEvent.pointerDown(screen.getByText('Inbox'), { button: 0, pointerId: 1, clientX: 10, clientY: 10 })
        rerenderWith([SETTINGS, INBOX])
        fireEvent.pointerUp(document.body, { pointerId: 1, clientX: 10, clientY: 10 })
        expect(onItemSelect).toHaveBeenCalledTimes(1)

        // Some results, such as the theme toggle, leave the search open, so the same row can be
        // activated again straight away. Base UI runs a keyboard Enter as `listItem.click()`,
        // which carries no click count.
        act(() => {
            screen.getByText('Inbox').click()
        })

        expect(onItemSelect).toHaveBeenCalledTimes(2)
        expect(onItemSelect).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'inbox' }), false)
    })

    it('cancels the selection when the pointer is dragged off the result', () => {
        renderResults([INBOX, SETTINGS])

        fireEvent.pointerDown(screen.getByText('Inbox'), { button: 0, pointerId: 1, clientX: 10, clientY: 10 })
        fireEvent.pointerUp(document.body, { pointerId: 1, clientX: 10, clientY: 300 })

        expect(onItemSelect).not.toHaveBeenCalled()
    })
})
