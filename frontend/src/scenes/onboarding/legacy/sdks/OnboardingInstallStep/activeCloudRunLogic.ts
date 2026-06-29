import { actions, kea, path, reducers } from 'kea'

import type { activeCloudRunLogicType } from './activeCloudRunLogicType'

export interface CloudRunHandle {
    taskId: string
    runId: string
}

/**
 * Holds the active cloud-run handle app-wide so the global progress FAB can keep showing a run after
 * the user advances past (or unmounts) the install step. Persisted so it also survives a refresh during
 * a long run. The install step writes it on kickoff; the FAB clears it on dismiss.
 */
export const activeCloudRunLogic = kea<activeCloudRunLogicType>([
    path(['scenes', 'onboarding', 'activeCloudRunLogic']),
    actions({
        setActiveCloudRun: (taskId: string, runId: string) => ({ taskId, runId }),
        clearActiveCloudRun: true,
        // Set by the inline install-step progress view while it's mounted, so the floating FAB hides
        // and the two never render the same run at once (mirrors wizardProgressTrackerLogic.panelMounted).
        setPanelMounted: (mounted: boolean) => ({ mounted }),
    }),
    reducers({
        activeCloudRun: [
            null as CloudRunHandle | null,
            { persist: true },
            {
                setActiveCloudRun: (_, { taskId, runId }) => ({ taskId, runId }),
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
])
