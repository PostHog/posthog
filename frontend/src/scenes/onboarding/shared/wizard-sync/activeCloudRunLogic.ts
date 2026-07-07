import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { projectLogic } from 'scenes/projectLogic'

import type { activeCloudRunLogicType } from './activeCloudRunLogicType'

export interface CloudRunHandle {
    taskId: string
    runId: string
    /** ISO timestamp stamped at kickoff so the sync widget can show elapsed time (the cloud stream
     * carries no start field). Optional: runs persisted before this field existed will not have it. */
    startedAt?: string
    /** Project the run belongs to. Optional: runs persisted before this field existed will not have
     * it — those are treated as stale and never surfaced (see `activeCloudRun`). */
    projectId?: number
}

// The persisted handle, but only when it belongs to the given project. Handles without a projectId
// predate the stamp and can't be attributed, so they're stale by definition.
export function scopedCloudRun(handle: CloudRunHandle | null, currentProjectId: number | null): CloudRunHandle | null {
    return handle?.projectId != null && handle.projectId === currentProjectId ? handle : null
}

/**
 * Holds the active cloud-run handle app-wide so the global progress FAB can keep showing a run after
 * the user advances past (or unmounts) the install step. Persisted so it also survives a refresh during
 * a long run. The install step writes it on kickoff; the FAB clears it on dismiss.
 *
 * The persisted handle lives in localStorage, which is shared across every account and project on this
 * browser — so `activeCloudRun` only surfaces a handle stamped with the current project. Without that
 * gate a fresh account inherits the previous account's run and greets the user with a progress widget
 * for a run that isn't theirs.
 */
export const activeCloudRunLogic = kea<activeCloudRunLogicType>([
    path(['scenes', 'onboarding', 'activeCloudRunLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        setActiveCloudRun: (taskId: string, runId: string, startedAt: string, projectId: number) => ({
            taskId,
            runId,
            startedAt,
            projectId,
        }),
        clearActiveCloudRun: true,
        // Set by the inline install-step progress view while it's mounted, so the floating FAB hides
        // and the two never render the same run at once (mirrors wizardProgressTrackerLogic.panelMounted).
        // Last-writer-wins boolean, not a refcount: at most ONE inline view may be mounted at a time,
        // or the first unmount un-hides the FAB while the second view is still on screen.
        setPanelMounted: (mounted: boolean) => ({ mounted }),
    }),
    reducers({
        persistedCloudRun: [
            null as CloudRunHandle | null,
            { persist: true },
            {
                setActiveCloudRun: (_, { taskId, runId, startedAt, projectId }) => ({
                    taskId,
                    runId,
                    startedAt,
                    projectId,
                }),
                clearActiveCloudRun: () => null,
            },
        ],
        panelMounted: [
            false,
            {
                setPanelMounted: (_, { mounted }) => mounted,
            },
        ],
    }),
    selectors({
        activeCloudRun: [
            (s) => [s.persistedCloudRun, s.currentProjectId],
            (persistedCloudRun, currentProjectId): CloudRunHandle | null =>
                scopedCloudRun(persistedCloudRun, currentProjectId),
        ],
    }),
])
