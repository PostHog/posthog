import { CloudRunHandle, MAX_CLOUD_RUN_AGE_MS, scopedCloudRun } from './activeCloudRunLogic'

const handle: CloudRunHandle = {
    taskId: 'task-1',
    runId: 'run-1',
    startedAt: '2026-01-01T00:00:00Z',
    projectId: 2,
}
const NOW = new Date('2026-01-01T00:05:00Z').getTime()

describe('scopedCloudRun', () => {
    it.each([
        // The persisted handle is browser-wide localStorage — a fresh account inheriting another
        // project's run must never surface it.
        ['a handle from another project', handle, 7, NOW, null],
        ['a legacy handle without a projectId', { ...handle, projectId: undefined }, 2, NOW, null],
        ['no current project resolved yet', handle, null, NOW, null],
        ['no handle at all', null, 2, NOW, null],
        ['a handle for the current project', handle, 2, NOW, handle],
        // A zombie run older than the age cap is expired outright, so its widget (and the 42h+
        // elapsed clock the ticket reported) can't follow the user around forever.
        [
            'a handle older than the age cap',
            handle,
            2,
            new Date(handle.startedAt!).getTime() + MAX_CLOUD_RUN_AGE_MS + 1000,
            null,
        ],
        // A legacy handle with no startedAt can't be aged out, but it's still surfaced (project scope
        // is the only gate for it) so a mid-run refresh of an older run isn't stranded.
        [
            'a handle with no startedAt',
            { ...handle, startedAt: undefined },
            2,
            NOW,
            { ...handle, startedAt: undefined },
        ],
    ])('returns %s correctly', (_name, persisted, currentProjectId, now, expected) => {
        expect(scopedCloudRun(persisted, currentProjectId, now)).toEqual(expected)
    })
})
