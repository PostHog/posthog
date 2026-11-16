import { MenuRowKind, visibleMenuRows } from './menuRowVisibility'

const ROW_CODES: Record<string, MenuRowKind> = { i: 'item', l: 'label', s: 'separator' }

function shownRows(rows: string): string {
    const codes = rows.split(' ')
    const visible = visibleMenuRows(codes.map((code) => ROW_CODES[code]))
    return codes.filter((_, index) => visible[index]).join(' ')
}

describe('visibleMenuRows', () => {
    test.each([
        ['submenu that opens with a group shows no separator above its label', 's l i i s i', 'l i i s i'],
        ['group that starts with a nested group shows only the nested label', 'i s l s l i i s s i', 'i s l i i s i'],
        ['group whose rows all render nothing keeps no label', 'i s l s s l i s', 'i s l i'],
        ['scene separators next to a group collapse into one', 'i s s s l i s s i', 'i s l i s i'],
        ['empty destructive footer leaves no trailing separator', 'i i s', 'i i'],
        ['destructive footer after the top-level rows', 'i i s i', 'i i s i'],
        ['search that matches nothing shows nothing', 's l s s l s s', ''],
        ['label at the end shows nothing under it', 's i s l', 'i'],
    ])('%s', (_, rows, expected) => {
        expect(shownRows(rows)).toEqual(expected)
    })
})
