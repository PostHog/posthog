import { deleteListItemSelectionRange } from './listModel'
import { NotebookListItem } from './types'
import { getInlineText } from './utils'

function makeItem(text: string, depth: number = 0, id?: string): NotebookListItem {
    return { id, children: text ? [{ type: 'text', text }] : [], depth }
}

describe('listModel', () => {
    describe('deleteListItemSelectionRange', () => {
        test.each([
            {
                name: 'deletes a range within a single item',
                items: ['alpha'],
                range: { firstItemIndex: 0, firstStart: 1, lastItemIndex: 0, lastEnd: 3 },
                replacementText: '',
                expectedTexts: ['aha'],
                expectedCaret: { itemIndex: 0, offset: 1 },
            },
            {
                name: 'empties a fully selected item but keeps it in the list',
                items: ['one', 'two', 'three'],
                range: { firstItemIndex: 0, firstStart: 0, lastItemIndex: 0, lastEnd: 3 },
                replacementText: '',
                expectedTexts: ['', 'two', 'three'],
                expectedCaret: { itemIndex: 0, offset: 0 },
            },
            {
                name: 'merges across items and removes the ones in between',
                items: ['alpha', 'beta', 'gamma'],
                range: { firstItemIndex: 0, firstStart: 2, lastItemIndex: 2, lastEnd: 3 },
                replacementText: '',
                expectedTexts: ['alma'],
                expectedCaret: { itemIndex: 0, offset: 2 },
            },
            {
                name: 'inserts replacement text where the selection started',
                items: ['alpha', 'beta', 'gamma'],
                range: { firstItemIndex: 0, firstStart: 2, lastItemIndex: 2, lastEnd: 3 },
                replacementText: 'X',
                expectedTexts: ['alXma'],
                expectedCaret: { itemIndex: 0, offset: 3 },
            },
            {
                name: 'clamps offsets that overshoot the item text',
                items: ['ab', 'cd'],
                range: { firstItemIndex: 0, firstStart: 5, lastItemIndex: 1, lastEnd: 9 },
                replacementText: '',
                expectedTexts: ['ab'],
                expectedCaret: { itemIndex: 0, offset: 2 },
            },
        ])('$name', ({ items, range, replacementText, expectedTexts, expectedCaret }) => {
            const deletion = deleteListItemSelectionRange(
                items.map((text) => makeItem(text)),
                range,
                replacementText
            )

            expect(deletion).not.toBeNull()
            expect(deletion?.items.map((item) => getInlineText(item.children))).toEqual(expectedTexts)
            expect(deletion?.caretItemIndex).toEqual(expectedCaret.itemIndex)
            expect(deletion?.caretOffset).toEqual(expectedCaret.offset)
        })

        test.each([
            {
                name: 'a collapsed range without replacement text',
                items: ['alpha'],
                range: { firstItemIndex: 0, firstStart: 2, lastItemIndex: 0, lastEnd: 2 },
            },
            {
                name: 'an out-of-bounds item index',
                items: ['alpha'],
                range: { firstItemIndex: 0, firstStart: 0, lastItemIndex: 3, lastEnd: 1 },
            },
        ])('returns null for $name', ({ items, range }) => {
            expect(
                deleteListItemSelectionRange(
                    items.map((text) => makeItem(text)),
                    range
                )
            ).toBeNull()
        })

        it('keeps the first item identity and depth when merging', () => {
            const items = [makeItem('parent', 0, 'item-a'), makeItem('child', 1, 'item-b')]

            const deletion = deleteListItemSelectionRange(items, {
                firstItemIndex: 0,
                firstStart: 3,
                lastItemIndex: 1,
                lastEnd: 2,
            })

            expect(deletion?.items).toHaveLength(1)
            expect(deletion?.items[0].id).toEqual('item-a')
            expect(deletion?.items[0].depth).toEqual(0)
            expect(deletion?.caretItemId).toEqual('item-a')
            expect(getInlineText(deletion?.items[0].children ?? [])).toEqual('parild')
        })
    })
})
