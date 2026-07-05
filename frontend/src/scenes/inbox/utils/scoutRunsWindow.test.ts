import { pluralize } from 'lib/utils/strings'

import { SignalScoutRunSummary } from '../types'
import {
    computeFleetSummary,
    computeScoutRollups,
    deriveRunOutcome,
    reconcileById,
    runMatchesFilter,
    ScoutRunOutcome,
    scoutReportActivityLabel,
} from './scoutRunsWindow'

const NOW = new Date('2026-06-27T22:00:00Z')

function makeRun(overrides: Partial<SignalScoutRunSummary> = {}): SignalScoutRunSummary {
    return {
        run_id: 'run-1',
        skill_name: 'signals-scout-dev-report-probe',
        skill_version: 1,
        status: 'completed',
        created_at: '2026-06-27T21:00:00Z',
        started_at: '2026-06-27T21:00:00Z',
        completed_at: '2026-06-27T21:02:00Z',
        summary: '',
        emitted_count: 0,
        emitted_finding_ids: [],
        emitted_report_ids: [],
        edited_report_ids: [],
        ...overrides,
    }
}

describe('scoutRunsWindow report channel', () => {
    // The report channel (emit_report/edit_report) is invisible to emitted_count, so a report-authoring
    // run used to read as "quiet / 0 signals emitted". These lock in that report activity counts as output.
    describe('deriveRunOutcome', () => {
        it.each<[string, Partial<SignalScoutRunSummary>, ScoutRunOutcome]>([
            ['authored a report, no findings → reported', { emitted_report_ids: ['r-1'] }, 'reported'],
            ['only edited a report, no findings → reported', { edited_report_ids: ['r-2'] }, 'reported'],
            ['no findings and no reports → quiet', {}, 'quiet'],
            [
                'findings win over report activity → emitted',
                { emitted_count: 2, emitted_finding_ids: ['f-1', 'f-2'], emitted_report_ids: ['r-1'] },
                'emitted',
            ],
        ])('%s', (_name, overrides, expected) => {
            expect(deriveRunOutcome(makeRun(overrides), NOW)).toEqual(expected)
        })
    })

    describe('runMatchesFilter', () => {
        it('keeps a report-authoring run out of Quiet and inside Emitted', () => {
            const run = makeRun({ emitted_report_ids: ['r-1'] })
            expect(runMatchesFilter(run, 'quiet')).toBe(false)
            expect(runMatchesFilter(run, 'emitted')).toBe(true)
        })

        it('keeps a genuinely quiet run inside Quiet and out of Emitted', () => {
            const run = makeRun()
            expect(runMatchesFilter(run, 'quiet')).toBe(true)
            expect(runMatchesFilter(run, 'emitted')).toBe(false)
        })
    })

    describe('scoutReportActivityLabel', () => {
        // Expected built via `pluralize` so the count↔word non-breaking space matches without hardcoding
        // an invisible character in the literal. The ` · ` separator uses normal spaces.
        it.each<[string, Partial<SignalScoutRunSummary>, string | null]>([
            ['authored only', { emitted_report_ids: ['r-1'] }, `${pluralize(1, 'report')} authored`],
            ['edited only (pluralized)', { edited_report_ids: ['r-1', 'r-2'] }, `${pluralize(2, 'report')} edited`],
            [
                'both authored and edited',
                { emitted_report_ids: ['r-1'], edited_report_ids: ['r-2'] },
                `${pluralize(1, 'report')} authored · ${pluralize(1, 'report')} edited`,
            ],
            ['no report activity', {}, null],
        ])('%s', (_name, overrides, expected) => {
            expect(scoutReportActivityLabel(makeRun(overrides))).toEqual(expected)
        })
    })

    describe('computeScoutRollups', () => {
        it('dedupes report ids across runs into the authored/edited sets', () => {
            const skill = 'signals-scout-dev-report-probe'
            const runs = [
                makeRun({ run_id: 'run-1', skill_name: skill, emitted_report_ids: ['r-1'] }),
                // The same report is edited by a later run — must not double-count, and stays distinct
                // from the authored set.
                makeRun({ run_id: 'run-2', skill_name: skill, edited_report_ids: ['r-1'] }),
                makeRun({ run_id: 'run-3', skill_name: skill, edited_report_ids: ['r-2'] }),
            ]
            const rollup = computeScoutRollups(runs).get(skill)!
            expect([...rollup.authoredReportIds]).toEqual(['r-1'])
            expect([...rollup.editedReportIds].sort()).toEqual(['r-1', 'r-2'])
        })
    })

    describe('computeFleetSummary', () => {
        it('counts a report-only run toward emit rate, matching the Emitted filter', () => {
            // Guards the divergence where the fleet emit rate counted only `emitted_count > 0` while the
            // per-scout "Emitted" chip counts report-channel output too — the two surfaces must agree.
            const rollups = computeScoutRollups([makeRun({ emitted_report_ids: ['r-1'] })])
            expect(computeFleetSummary([], rollups).emitRate).toEqual(1)
        })
    })

    describe('reconcileById', () => {
        it('keeps the previous reference for unchanged items and the fresh one for changed items', () => {
            // Every runs-window poll returns freshly parsed objects; reconcileById is what preserves
            // identity so memoized rows only re-render on real change. If it degrades to `return next`,
            // unchanged runs churn references every 60s and the memo is silently defeated.
            const prevUnchanged = makeRun({ run_id: 'run-1', emitted_count: 1 })
            const prevChanged = makeRun({ run_id: 'run-2', status: 'running' })

            const nextUnchanged = makeRun({ run_id: 'run-1', emitted_count: 1 })
            const nextChanged = makeRun({ run_id: 'run-2', status: 'completed' })
            const nextNew = makeRun({ run_id: 'run-3' })

            const result = reconcileById(
                [prevUnchanged, prevChanged],
                [nextUnchanged, nextChanged, nextNew],
                (run) => run.run_id
            )

            expect(result[0]).toBe(prevUnchanged)
            expect(result[1]).toBe(nextChanged)
            expect(result[2]).toBe(nextNew)
        })

        it('returns the next array untouched when there is no previous window', () => {
            const next = [makeRun({ run_id: 'run-1' })]
            expect(reconcileById([], next, (run) => run.run_id)).toBe(next)
        })

        it('never reuses items the isReusable predicate rejects, even when deep-equal', () => {
            // A running run's row renders a wall-clock duration: reusing its reference would let the
            // memoized row skip the poll re-render and freeze the ticking timer.
            const prev = makeRun({ run_id: 'run-1', status: 'in_progress' })
            const next = makeRun({ run_id: 'run-1', status: 'in_progress' })
            const result = reconcileById(
                [prev],
                [next],
                (run) => run.run_id,
                (run) => run.status !== 'in_progress'
            )
            expect(result[0]).toBe(next)
        })
    })
})
