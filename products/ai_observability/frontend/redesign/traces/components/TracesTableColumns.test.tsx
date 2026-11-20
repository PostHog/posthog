import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { initKeaTests } from '~/test/init'

import type { TraceListItemApi } from '../../../generated/api.schemas'
import { makeTraceListItem } from '../testFixtures'
import { tracesTableColumns } from './TracesTableColumns'

function renderRows(items: TraceListItemApi[]): { headers: string[]; cells: string[]; nameHref: string | null } {
    initKeaTests()
    const { container } = render(
        <LemonTable<TraceListItemApi>
            columns={tracesTableColumns({ linkTo: (row) => `/traces/${row.id}` })}
            dataSource={items}
            rowKey={(row) => row.id}
        />
    )
    const texts = (selector: string): string[] =>
        Array.from(container.querySelectorAll(selector)).map((cell) => cell.textContent?.trim() ?? '')
    return {
        headers: texts('thead th').filter(Boolean),
        cells: texts('tbody td'),
        nameHref: container.querySelector('[data-attr="trace-name-link"]')?.getAttribute('href') ?? null,
    }
}

describe('tracesTableColumns', () => {
    afterEach(cleanup)

    it("renders a trace's cells in the row's order", () => {
        const { headers, cells, nameHref } = renderRows([
            makeTraceListItem({
                id: 'trace-a',
                name: 'rag-query',
                createdAt: '2026-09-01T11:43:00Z',
                isSupportTrace: true,
                hasError: true,
                errorCount: 3,
                firstError: 'Context window exceeded',
                toolsCalled: ['search_docs', 'read_file', 'run_sql', 'send_email'],
                review: {
                    review: { reviewedBy: 'Ana', reviewedAt: '2026-09-01T12:00:00Z', comment: null, scores: [] },
                    queue: null,
                },
            }),
        ])

        expect(headers).toEqual(['Time', 'Name', 'Errors', 'Latency', 'Tokens', 'Cost', 'Tools', 'Review'])
        expect(cells).toEqual([
            'Sep 1, 11:43',
            'rag-querySupport',
            'Context window exceeded+2',
            '2.31s',
            '1,840 in · 212 out',
            '$0.0021',
            'search_docsread_filerun_sql+1',
            'Reviewed',
        ])
        expect(nameHref).toContain('/traces/trace-a')
    })

    it('renders a placeholder for a null name, a null latency and an error without text', () => {
        const { cells } = renderRows([
            makeTraceListItem({
                name: null,
                hasError: true,
                errorCount: 1,
                firstError: null,
                totals: {
                    costUsd: null,
                    inputTokens: null,
                    outputTokens: null,
                    cacheReadTokens: null,
                    cacheWriteTokens: null,
                    latencyMs: null,
                },
            }),
        ])

        expect(cells.slice(1, 6)).toEqual(['Untitled trace', 'Unknown error', '-', '-', '-'])
    })

    it('hints that the totals are partial only on a trace whose totals are partial', async () => {
        const totals = makeTraceListItem().totals
        renderRows([
            makeTraceListItem({ id: 'whole', totals: { ...totals, latencyMs: 1000 } }),
            makeTraceListItem({ id: 'partial', totals: { ...totals, latencyMs: 2310 }, totalsPartial: true }),
        ])

        for (const latency of ['1s', '2.31s']) {
            const value = screen.getByText(latency)
            fireEvent.pointerEnter(value, { pointerType: 'mouse' })
            fireEvent.mouseEnter(value)
            fireEvent.pointerMove(value, { pointerType: 'mouse' })
            fireEvent.mouseMove(value)
        }

        expect(await screen.findAllByText(/come from its earliest steps only/)).toHaveLength(1)
    })
})
