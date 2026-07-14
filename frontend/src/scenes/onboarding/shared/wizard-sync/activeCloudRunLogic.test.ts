import { CloudRunHandle, scopedCloudRun } from './activeCloudRunLogic'

const handle: CloudRunHandle = {
    taskId: 'task-1',
    runId: 'run-1',
    startedAt: '2026-01-01T00:00:00Z',
    projectId: 2,
}

describe('scopedCloudRun', () => {
    it.each([
        // The persisted handle is browser-wide localStorage — a fresh account inheriting another
        // project's run must never surface it.
        ['a handle from another project', handle, 7, null],
        ['a legacy handle without a projectId', { ...handle, projectId: undefined }, 2, null],
        ['no current project resolved yet', handle, null, null],
        ['no handle at all', null, 2, null],
        ['a handle for the current project', handle, 2, handle],
    ])('returns %s correctly', (_name, persisted, currentProjectId, expected) => {
        expect(scopedCloudRun(persisted, currentProjectId)).toEqual(expected)
    })
})
