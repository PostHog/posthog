import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import type { TraceApi } from '../../../generated/api.schemas'
import { makeTraceCluster, makeTraceResource } from '../testFixtures'
import { TraceSummaryBar, TraceSummaryBarProps } from './TraceSummaryBar'

const NO_EVALS = { passed: 0, failed: 0, unrated: 0, nodes: [] }
const NO_FEEDBACK = { total: 0, thumbsUp: 0, thumbsDown: 0 }

function renderBar(props: Partial<TraceSummaryBarProps> = {}): void {
    const trace = makeTraceResource()
    render(<TraceSummaryBar overview={trace} person={trace.person} {...props} />)
}

describe('TraceSummaryBar', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows no evals, feedback or clusters chip when there is nothing to count', () => {
        renderBar({
            clusters: [],
            evals: { summary: NO_EVALS, onClick: () => {} },
            feedback: { summary: NO_FEEDBACK, onClick: () => {} },
        })

        expect(screen.queryByText(/^Evals/)).toBeNull()
        expect(screen.queryByText(/^Feedback/)).toBeNull()
        expect(document.querySelector('[data-attr="trace-view-cluster-chip"]')).toBeNull()
    })

    it.each([
        ['graded results', { passed: 4, failed: 1, unrated: 0 }, 'Evals 4/5 passed'],
        ['only unrated results', { passed: 0, failed: 0, unrated: 3 }, 'Evals 3 not graded'],
    ])('counts %s on the evals chip', (_name, counts, text) => {
        renderBar({ evals: { summary: { ...counts, nodes: [] }, onClick: () => {} } })

        expect(screen.getByText(text)).toBeTruthy()
    })

    it('leads with the first cluster by its label, links it to its page and counts the others', () => {
        renderBar({
            clusters: [
                makeTraceCluster({ runId: 'run-a', clusterId: 3, label: 'Billing questions' }),
                makeTraceCluster({ runId: 'run-b', clusterId: -1, title: null, label: 'Outliers', isOutlier: true }),
                makeTraceCluster({ runId: 'run-c', clusterId: 7, title: null, label: 'Cluster 7' }),
            ],
        })

        expect(screen.getByText('Billing questions')).toBeTruthy()
        expect(document.querySelector('[data-attr="trace-view-cluster-chip"]')?.getAttribute('href')).toContain(
            urls.aiObservabilityCluster('run-a', 3)
        )
        expect(screen.getByText('+2')).toBeTruthy()
    })

    it('links the person to their page', () => {
        renderBar()

        expect(screen.getByText('ada@example.com').closest('a')?.getAttribute('href')).toContain(
            urls.personByDistinctId('user-1')
        )
    })

    it.each([
        ['1,840 in', { totalsPartial: true }, true],
        ['2.31s', { totalsPartial: true }, false],
        ['$0.0021', { totalsPartial: true }, false],
        ['1,840 in', { costAndLatencyPartial: true }, false],
        ['2.31s', { costAndLatencyPartial: true }, true],
        ['$0.0021', { costAndLatencyPartial: true }, true],
    ])(
        'the stat %s of a trace with %p shows the partial hint: %s',
        async (text, partial: Partial<TraceApi>, hinted) => {
            const trace = makeTraceResource({
                totals: { ...makeTraceResource().totals, costUsd: 0.0021, inputTokens: 1840, latencyMs: 2310 },
                ...partial,
            })
            render(<TraceSummaryBar overview={trace} />)

            const value = screen.getByText(text)
            fireEvent.pointerEnter(value, { pointerType: 'mouse' })
            fireEvent.mouseEnter(value)
            fireEvent.pointerMove(value, { pointerType: 'mouse' })
            fireEvent.mouseMove(value)

            const hint = screen.findByText(/covers those steps only/)
            await (hinted ? await expect(hint).resolves.toBeTruthy() : await expect(hint).rejects.toThrow())
        }
    )

    it('names the thumbs on the feedback chip', () => {
        renderBar({ feedback: { summary: { total: 1, thumbsUp: 1, thumbsDown: 0 }, onClick: () => {} } })

        expect(screen.getByLabelText('1 thumbs up, 0 thumbs down, 1 feedback in total')).toBeTruthy()
    })
})
