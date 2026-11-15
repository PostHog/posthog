import { FlatMenuRowKind, visibleFlatMenuRows } from './flatMenuRows'

const ROW_CODES: Record<string, FlatMenuRowKind> = { i: 'item', l: 'label', s: 'separator' }

function shownRows(rows: string): string {
    const codes = rows.split(' ')
    const visible = visibleFlatMenuRows(codes.map((code) => ROW_CODES[code]))
    return codes.filter((_, index) => visible[index]).join(' ')
}

describe('visibleFlatMenuRows', () => {
    test.each([
        ['unlabeled File section, then a labeled Edit section', 's i i s s l i s', 'i i s l i'],
        ['section whose rows the search removed keeps no label', 's i s s l s s l i s', 'i s l i'],
        ['section that starts with a flattened submenu shows only the submenu label', 's l s l i i s i s', 'l i i s i'],
        ['empty destructive footer leaves no trailing separator', 's i s s', 'i'],
        ['destructive footer after the list', 's l i s s i', 'l i s i'],
        ['scene separators inside a section collapse into one', 's i s s s i s', 'i s i'],
        ['no match anywhere shows nothing', 's l s s l s s', ''],
        ['label at the end shows nothing under it', 's i s l', 'i'],
    ])('%s', (_, rows, expected) => {
        expect(shownRows(rows)).toEqual(expected)
    })
})
