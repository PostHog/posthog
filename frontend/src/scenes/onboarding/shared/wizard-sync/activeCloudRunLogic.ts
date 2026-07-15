import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { tasksActiveWizardRunRetrieve } from 'products/tasks/frontend/generated/api'

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
        values: [projectLogic, ['currentProjectId'], userLogic, ['isProvisionedUser']],
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
        // and the two never render the same run at once.
        // Last-writer-wins boolean, not a refcount: at most ONE inline view may be mounted at a time,
        // or the first unmount un-hides the FAB while the second view is still on screen.
        setPanelMounted: (mounted: boolean) => ({ mounted }),
        // Ask the server whether the current project has an active wizard cloud run, seeding the
        // handle when the drop flow started the run server-side (so no local handle was ever written).
        hydrateFromServer: true,
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
        // The two inputs hydrateFromServer needs, both of which load asynchronously after mount.
        // We wait for this to flip true rather than firing once on mount, so a run started for a
        // provisioned user before their user/project loaded still gets hydrated.
        canHydrateFromServer: [
            (s) => [s.isProvisionedUser, s.currentProjectId],
            (isProvisionedUser, currentProjectId): boolean => isProvisionedUser && currentProjectId != null,
        ],
    }),
    listeners(({ actions, values }) => ({
        hydrateFromServer: async () => {
            // The drop flow starts the run server-side, so a freshly-signed-in provisioned user has
            // no localStorage handle. Only they need the extra request; everyone else already has a
            // client-written handle if a run exists.
            if (!values.isProvisionedUser) {
                return
            }
            const projectId = values.currentProjectId
            if (projectId == null || values.activeCloudRun) {
                // Never clobber a fresher local handle — server hydration is a fallback only.
                return
            }
            try {
                const handle = await tasksActiveWizardRunRetrieve(String(projectId))
                // 204 → void; nothing to surface.
                if (!handle || values.activeCloudRun) {
                    return
                }
                actions.setActiveCloudRun(
                    handle.task_id,
                    handle.run_id,
                    handle.started_at ?? new Date().toISOString(),
                    projectId
                )
            } catch {
                // Best-effort: a failed hydration just means no FAB, same as before.
            }
        },
    })),
    subscriptions(({ actions }) => ({
        // Fires once on mount (with the current value) and again whenever readiness changes, so
        // hydration runs as soon as both inputs are available — not just if they happened to be
        // ready at mount. hydrateFromServer is idempotent, so a no-op false value is harmless.
        canHydrateFromServer: (canHydrate: boolean) => {
            if (canHydrate) {
                actions.hydrateFromServer()
            }
        },
    })),
])
