import { OriginProduct, Task, TaskRun, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { mergeSignalRuns } from './inboxSceneLogic'
import { SignalScoutRunSummary } from './types'

function scoutRun(overrides: Partial<SignalScoutRunSummary> = {}): SignalScoutRunSummary {
    return {
        run_id: 'run-1',
        skill_name: 'signals-scout-error-tracking',
        skill_version: 1,
        status: 'completed',
        created_at: '2026-06-11T10:00:00Z',
        started_at: '2026-06-11T10:00:00Z',
        completed_at: null,
        task_id: 'task-scout',
        summary: '',
        emitted_count: 0,
        emitted_finding_ids: [],
        emitted_report_ids: [],
        edited_report_ids: [],
        ...overrides,
    }
}

function signalTask(overrides: Partial<Task> = {}): Task {
    return {
        id: 'task-signal',
        task_number: null,
        slug: '',
        title: 'Crash on login',
        description: '',
        origin_product: OriginProduct.SIGNAL_REPORT,
        repository: null,
        github_integration: null,
        signal_report: 'report-1',
        json_schema: null,
        internal: false,
        latest_run: null,
        created_at: '2026-06-11T09:00:00Z',
        updated_at: '2026-06-11T09:00:00Z',
        created_by: null,
        ...overrides,
    }
}

describe('mergeSignalRuns', () => {
    it('drops scout runs without a backing task_id (they cannot deep-link to a task)', () => {
        const merged = mergeSignalRuns([scoutRun({ task_id: null }), scoutRun({ task_id: 'task-ok' })], [])
        expect(merged.map((r) => r.task_id)).toEqual(['task-ok'])
    })

    it('interleaves scout and signal rows newest-first by created_at', () => {
        const merged = mergeSignalRuns(
            [scoutRun({ task_id: 'scout-old', created_at: '2026-06-10T00:00:00Z' })],
            [signalTask({ id: 'signal-new', created_at: '2026-06-12T00:00:00Z' })]
        )
        expect(merged.map((r) => r.task_id)).toEqual(['signal-new', 'scout-old'])
    })

    it('tags kind and title per source (scout → skill_name, signal → report title)', () => {
        const [scoutRow, signalRow] = mergeSignalRuns(
            [scoutRun({ task_id: 'scout', skill_name: 'signals-scout-surveys', created_at: '2026-06-11T11:00:00Z' })],
            [signalTask({ id: 'signal', title: 'Slow query', created_at: '2026-06-11T08:00:00Z' })]
        )
        expect(scoutRow).toMatchObject({ kind: 'scout', title: 'signals-scout-surveys', report_id: null })
        expect(signalRow).toMatchObject({ kind: 'signal', title: 'Slow query', report_id: 'report-1' })
    })

    it('falls back to the task timestamp and a null status when a signal task has no run', () => {
        const [row] = mergeSignalRuns([], [signalTask({ latest_run: null, created_at: '2026-06-11T07:00:00Z' })])
        expect(row).toMatchObject({ status: null, created_at: '2026-06-11T07:00:00Z' })
    })

    it("maps the latest run's task status to the scout status string, and uses the run's timestamp", () => {
        const latest_run = {
            status: TaskRunStatus.IN_PROGRESS,
            created_at: '2026-06-11T12:00:00Z',
        } as TaskRun
        const [row] = mergeSignalRuns([], [signalTask({ latest_run, created_at: '2026-06-11T07:00:00Z' })])
        // The `TaskRunStatus` enum is bridged to the equivalent `SignalScoutRunStatus` string the row
        // field holds (here 'in_progress'), and the run's own timestamp wins over the task's.
        expect(row).toMatchObject({ status: 'in_progress', created_at: '2026-06-11T12:00:00Z' })
    })
})
