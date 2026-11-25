import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { initKeaTests } from '~/test/init'

import type { TraceListItemApi } from '../../../generated/api.schemas'
import { makeLoadedTraceCells, makeTraceListItem, makeTracePreview, makeUnreadTraceCells, ready } from '../testFixtures'
import { TracesTableCells, tracesTableColumns } from './TracesTableColumns'

const NO_CELLS: TracesTableCells = { previews: new Map(), people: new Map(), sentiments: new Map() }

function renderRows(
    items: TraceListItemApi[],
    cells: TracesTableCells = NO_CELLS
): { headers: string[]; cells: string[]; nameHref: string | null; rerender: (cells: TracesTableCells) => string[] } {
    initKeaTests()
    const table = (tableCells: TracesTableCells): JSX.Element => (
        <LemonTable<TraceListItemApi>
            columns={tracesTableColumns({ linkTo: (row) => `/traces/${row.id}`, cells: tableCells })}
            dataSource={items}
            rowKey={(row) => row.id}
        />
    )
    const { container, rerender } = render(table(cells))
    const texts = (selector: string): string[] =>
        Array.from(container.querySelectorAll(selector)).map((cell) => cell.textContent?.trim() ?? '')
    return {
        headers: texts('thead th').filter(Boolean),
        cells: texts('tbody td'),
        nameHref: container.querySelector('[data-attr="trace-name-link"]')?.getAttribute('href') ?? null,
        rerender: (nextCells) => {
            rerender(table(nextCells))
            return texts('tbody td')
        },
    }
}

describe('tracesTableColumns', () => {
    afterEach(cleanup)

    it("renders a trace's cells in the row's order", () => {
        const { headers, cells, nameHref } = renderRows(
            [
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
            ],
            makeLoadedTraceCells(['trace-a'])
        )

        expect(headers).toEqual([
            'Time',
            'Name',
            'Person',
            'Input',
            'Output',
            'Errors',
            'Latency',
            'Tokens',
            'Cost',
            'Sentiment',
            'Tools',
            'Review',
        ])
        expect(cells).toEqual([
            'Sep 1, 11:43',
            'rag-querySupport',
            'AAna Example',
            'Why was I charged twice this month?',
            'You were charged once for your plan and once for extra seats added on the 12th.',
            'Context window exceeded+2',
            '2.31s',
            '1,840 in · 212 out',
            '$0.0021',
            'Positive 82%',
            'search_docsread_filerun_sql+1',
            'Reviewed',
        ])
        expect(nameHref).toContain('/traces/trace-a')
    })

    it('renders a placeholder for a null name, a null latency, an error without text and empty cells', () => {
        const { cells } = renderRows(
            [
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
            ],
            {
                previews: new Map([['trace-1', ready(makeTracePreview('trace-1', { input: null, output: null }))]]),
                people: new Map([['trace-1', ready(null)]]),
                sentiments: new Map([['trace-1', ready(null)]]),
            }
        )

        expect(cells.slice(1, 10)).toEqual(['Untitled trace', '-', '-', '-', 'Unknown error', '-', '-', '-', '-'])
    })

    it('shows the slow cells loading until their values arrive', () => {
        const { cells, rerender } = renderRows(
            [makeTraceListItem({ id: 'trace-a' })],
            makeUnreadTraceCells(['trace-a'], 'loading')
        )
        const slowCells = (texts: string[]): string[] => [texts[2], texts[3], texts[4], texts[9]]

        expect(slowCells(cells)).toEqual(['Loading…', 'Loading…', 'Loading…', 'Loading…'])
        expect(slowCells(rerender(makeLoadedTraceCells(['trace-a'])))).toEqual([
            'AAna Example',
            'Why was I charged twice this month?',
            'You were charged once for your plan and once for extra seats added on the 12th.',
            'Positive 82%',
        ])
    })

    it.each([
        ['1,840 in · 212 out', {}, false],
        ['1,840 in · 212 out', { totalsPartial: true }, true],
        ['2.31s', { totalsPartial: true }, false],
        ['$0.0021', { totalsPartial: true }, false],
        ['1,840 in · 212 out', { costAndLatencyPartial: true }, false],
        ['2.31s', { costAndLatencyPartial: true }, true],
        ['$0.0021', { costAndLatencyPartial: true }, true],
    ])(
        'the %s cell of a trace with %p shows the partial hint: %s',
        async (text, partial: Partial<TraceListItemApi>, hinted) => {
            renderRows([makeTraceListItem(partial)])

            const value = screen.getByText(text)
            fireEvent.pointerEnter(value, { pointerType: 'mouse' })
            fireEvent.mouseEnter(value)
            fireEvent.pointerMove(value, { pointerType: 'mouse' })
            fireEvent.mouseMove(value)

            const hint = screen.findByText(/covers those steps only/)
            await (hinted ? await expect(hint).resolves.toBeTruthy() : await expect(hint).rejects.toThrow())
        }
    )
})
