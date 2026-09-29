import { router } from 'kea-router'

import { newInternalTab } from 'lib/utils/newInternalTab'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { createSessionsRowProps } from './sessionsColumns'

jest.mock('lib/utils/newInternalTab', () => ({ newInternalTab: jest.fn() }))

describe('createSessionsRowProps', () => {
    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.SessionsQuery, select: ['$start_timestamp', 'session_id'] },
    }

    beforeEach(() => {
        initKeaTests()
        jest.mocked(newInternalTab).mockClear()
    })

    afterEach(() => {
        window.getSelection()?.removeAllRanges()
    })

    function clickRow(
        record: unknown,
        target: HTMLElement = document.createElement('td'),
        modifiers: { metaKey?: boolean; ctrlKey?: boolean } = {}
    ): void {
        const props = createSessionsRowProps(query)?.(record) ?? {}
        props.onClick?.({
            target,
            metaKey: false,
            ctrlKey: false,
            ...modifiers,
        } as unknown as React.MouseEvent<HTMLTableRowElement>)
    }

    it('opens the session profile when the user clicks a plain cell', () => {
        clickRow({ result: ['2024-01-01T00:00:00Z', 'abc-123'] })

        expect(router.values.location.pathname).toContain('/sessions/abc-123')
    })

    it.each([{ metaKey: true }, { ctrlKey: true }])('opens the session profile in a new tab with %o', (modifiers) => {
        const start = router.values.location.pathname

        clickRow({ result: ['2024-01-01T00:00:00Z', 'abc-123'] }, undefined, modifiers)

        expect(newInternalTab).toHaveBeenCalledWith(expect.stringContaining('/sessions/abc-123'))
        expect(router.values.location.pathname).toEqual(start)
    })

    it('keeps the text selection when the user drags across a cell', () => {
        const start = router.values.location.pathname
        const cell = document.createElement('td')
        cell.textContent = 'abc-123'
        document.body.appendChild(cell)
        window.getSelection()?.selectAllChildren(cell)

        clickRow({ result: ['2024-01-01T00:00:00Z', 'abc-123'] }, cell)

        expect(router.values.location.pathname).toEqual(start)
        cell.remove()
    })

    it.each([
        ['a link in the row', 'a'],
        ['a button in the row', 'button'],
        ['an input in the row', 'input'],
    ])('leaves navigation to %s', (_, tagName) => {
        const start = router.values.location.pathname
        const parent = document.createElement(tagName)
        const target = document.createElement('span')
        parent.appendChild(target)

        clickRow({ result: ['2024-01-01T00:00:00Z', 'abc-123'] }, target)

        expect(router.values.location.pathname).toEqual(start)
    })

    it('gives day label rows no click handler', () => {
        expect(createSessionsRowProps(query)?.({ label: 'January 1, 2024' })).toEqual({})
    })
})
