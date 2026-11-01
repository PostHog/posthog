import { render } from '@testing-library/react'
import { Provider } from 'kea'
import type { ReactNode } from 'react'

import { dayjs } from 'lib/dayjs'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'

import { buildSampleTable } from './buildSampleTable'
import { type SampleRowsSource, samplePlaceholderColumn } from './sampleRows'

const NOW = dayjs('2026-10-23T12:00:00.000Z')

function eventsTable(select: string[], hiddenColumns?: string[]): DataTableNode {
    return setLatestVersionsOnQuery({
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.EventsQuery, select },
        hiddenColumns,
    }) as DataTableNode
}

function sampleSource({
    values = {},
    excludedColumns = [],
}: {
    values?: Record<string, unknown>
    excludedColumns?: string[]
}): SampleRowsSource {
    return {
        buildRows: (columns) => [
            { result: columns.map((column) => (column in values ? values[column] : samplePlaceholderColumn)) },
        ],
        dataAttr: 'test-table-sample-data',
        excludedColumns,
    }
}

function cellText(cell: ReactNode): string | null {
    return render(<Provider>{cell}</Provider>).container.textContent
}

describe('buildSampleTable', () => {
    beforeEach(() => initKeaTests())

    it.each([
        ['the * column', ['*', 'a', 'b', 'c', 'd', 'e'], [], []],
        ['a hidden column', ['a', 'hidden', 'b', 'c', 'd', 'e'], ['hidden'], []],
        ['an excluded column', ['a', 'excluded', 'b', 'c', 'd', 'e'], [], ['excluded']],
    ])('removes %s before it caps the columns', (_, columns, hiddenColumns, excludedColumns) => {
        const table = buildSampleTable(
            sampleSource({ excludedColumns }),
            columns,
            eventsTable(columns, hiddenColumns),
            undefined,
            NOW
        )

        expect(table.header).toEqual(['a', 'b', 'c', 'd'])
    })

    it('renders each value with its own column when a column before it is removed', () => {
        const columns = ['*', 'event', 'properties.$browser']
        const source = sampleSource({ values: { event: '$pageview', 'properties.$browser': 'Chrome' } })

        const table = buildSampleTable(source, columns, eventsTable(columns), undefined, NOW)

        expect(table.rows[0].map(cellText)).toEqual(['Pageview', 'Chrome'])
    })

    it('leaves only placeholder cells empty, so a real null still renders', () => {
        const columns = ['event', 'distinct_id']
        const source = sampleSource({ values: { event: samplePlaceholderColumn, distinct_id: null } })

        const table = buildSampleTable(source, columns, eventsTable(columns), undefined, NOW)

        const [placeholderCell, nullCell] = table.rows[0]
        expect(placeholderCell).toBeNull()
        expect(cellText(nullCell)).toBe('—')
    })
})
