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
        readonly pointerType: string
        constructor(type: string, init: PointerEventInit = {}) {
            super(type, init)
            this.pointerId = init.pointerId ?? 0
            this.pointerType = init.pointerType ?? ''
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

        fireEvent.pointerDown(screen.getByText('Inbox'), {
            button: 0,
            pointerId: 1,
            pointerType: 'mouse',
            clientX: 10,
            clientY: 10,
        })
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

        fireEvent.pointerDown(row, { button: 0, pointerId: 1, pointerType: 'mouse', clientX: 10, clientY: 10 })
        fireEvent.pointerUp(row, { pointerId: 1, clientX: 10, clientY: 10 })
        // `detail` is the click count, which every click a pointer makes carries.
        fireEvent.click(row, { clientX: 10, clientY: 10, detail: 1 })

        expect(onItemSelect).toHaveBeenCalledTimes(1)
    })

    it('selects on Enter after the list move swallowed the click', () => {
        const { rerenderWith } = renderResults([INBOX, SETTINGS])

        fireEvent.pointerDown(screen.getByText('Inbox'), {
            button: 0,
            pointerId: 1,
            pointerType: 'mouse',
            clientX: 10,
            clientY: 10,
        })
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

    // Each of these ends the gesture without a release on the pressed result, so the release that
    // does arrive must select nothing.
    test.each([
        [
            'the pointer is dragged off the result',
            (): void => {
                fireEvent.pointerUp(document.body, { pointerId: 1, clientX: 10, clientY: 300 })
            },
        ],
        [
            'the window loses focus while the press is held',
            (): void => {
                // A pointer that leaves the window can take both release events with it, so the
                // release below is the first one the hook sees.
                fireEvent.blur(window)
                fireEvent.pointerUp(screen.getByText('Inbox'), { pointerId: 1, clientX: 10, clientY: 10 })
            },
        ],
        [
            'a second press starts before the release',
            (): void => {
                fireEvent.pointerDown(document.body, {
                    button: 0,
                    pointerId: 1,
                    pointerType: 'mouse',
                    clientX: 10,
                    clientY: 10,
                })
                fireEvent.pointerUp(screen.getByText('Inbox'), { pointerId: 1, clientX: 10, clientY: 10 })
            },
        ],
    ])('cancels the selection when %s', (_case, release) => {
        renderResults([INBOX, SETTINGS])

        fireEvent.pointerDown(screen.getByText('Inbox'), {
            button: 0,
            pointerId: 1,
            pointerType: 'mouse',
            clientX: 10,
            clientY: 10,
        })
        release()

        expect(onItemSelect).not.toHaveBeenCalled()
    })

    it('leaves a touch press to the click path', () => {
        renderResults([INBOX, SETTINGS])
        const row = screen.getByText('Inbox')

        // A result is also a context menu trigger, which opens on a motionless touch press and
        // sends no pointercancel, so activating on the release would select the result behind
        // the menu it just opened.
        fireEvent.pointerDown(row, { button: 0, pointerId: 1, pointerType: 'touch', clientX: 10, clientY: 10 })
        fireEvent.pointerUp(row, { pointerId: 1, clientX: 10, clientY: 10 })
        expect(onItemSelect).not.toHaveBeenCalled()

        // A tap that opens no menu still selects, through the click the browser synthesizes.
        fireEvent.click(row, { clientX: 10, clientY: 10, detail: 1 })
        expect(onItemSelect).toHaveBeenCalledTimes(1)
    })
})
