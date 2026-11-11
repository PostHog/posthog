import { changedOnlyTraceDrawerParams, opensTraceDrawer } from './traceDrawerRows'

type DrawerClick = Parameters<typeof opensTraceDrawer>[0]

const LINK = '[data-attr="trace-link"]'

function click(target: EventTarget, row: Element, modifiers: { metaKey?: boolean } = {}): DrawerClick {
    return {
        target,
        currentTarget: row,
        button: 0,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        altKey: false,
        ...modifiers,
    }
}

describe('changedOnlyTraceDrawerParams', () => {
    const list = { pathname: '/list', searchParams: { tab: 'usage', trace: 'a' } }

    it.each([
        ['another trace', { ...list, searchParams: { tab: 'usage', trace: 'b' } }, true],
        ['a closed drawer', { ...list, searchParams: { tab: 'usage' } }, true],
        ['the same location', list, false],
        ['another list param as well', { ...list, searchParams: { tab: 'code', trace: 'b' } }, false],
        ['another path as well', { pathname: '/other', searchParams: { tab: 'usage', trace: 'b' } }, false],
    ])('for %s', (_name, next, expected) => {
        expect(changedOnlyTraceDrawerParams(list, next)).toBe(expected)
    })
})

describe('opensTraceDrawer', () => {
    const row = document.createElement('tr')
    row.innerHTML =
        '<td data-attr="cell">cell</td><td><a data-attr="trace-link">trace</a><a data-attr="other-link">other</a></td>'
    const part = (name: string): Element => row.querySelector(`[data-attr="${name}"]`) ?? row

    it.each([
        ['a plain cell on a list that opens from the row', 'cell', true, true],
        ['a plain cell on a list that opens from its links only', 'cell', false, false],
        ['the trace link on a list that opens from its links only', 'trace-link', false, true],
        ['another link', 'other-link', true, false],
    ])('on %s', (_name, target, rowClick, expected) => {
        expect(opensTraceDrawer(click(part(target), row), LINK, rowClick)).toBe(expected)
    })

    it('leaves a Cmd-click to the browser', () => {
        expect(opensTraceDrawer(click(part('trace-link'), row, { metaKey: true }), LINK, true)).toBe(false)
    })

    it('ignores a click from a portal outside the row', () => {
        expect(opensTraceDrawer(click(document.createElement('div'), row), LINK, true)).toBe(false)
    })
})
