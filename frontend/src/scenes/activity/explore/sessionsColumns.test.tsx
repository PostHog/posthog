import { router } from 'kea-router'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { createSessionsRowProps } from './sessionsColumns'

describe('createSessionsRowProps', () => {
    const query: DataTableNode = {
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.SessionsQuery, select: ['$start_timestamp', 'session_id'] },
    }

    beforeEach(() => {
        initKeaTests()
    })

    function clickRow(record: unknown, target: HTMLElement = document.createElement('td')): void {
        const props = createSessionsRowProps(query)?.(record) ?? {}
        props.onClick?.({ target, metaKey: false, ctrlKey: false } as unknown as React.MouseEvent<HTMLTableRowElement>)
    }

    it('opens the session profile when the user clicks a plain cell', () => {
        clickRow({ result: ['2024-01-01T00:00:00Z', 'abc-123'] })

        expect(router.values.location.pathname).toContain('/sessions/abc-123')
    })

    it.each([
        ['a link in the row', 'a'],
        ['a button in the row', 'button'],
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
