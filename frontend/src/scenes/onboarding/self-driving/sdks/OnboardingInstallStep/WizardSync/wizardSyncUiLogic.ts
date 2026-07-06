import { actions, kea, path, reducers } from 'kea'

import type { wizardSyncUiLogicType } from './wizardSyncUiLogicType'

/**
 * UI state for the detached wizard sync widget, shared app-wide (mounted by WizardSyncFab):
 *   - `dismissedKey`: the run the user minimized. Keyed by run id (cloud) or session id (local) so a
 *     fresh run is never born already-minimized, and a minimize survives navigation (persisted).
 *   - `dialogOpen`: whether the "all the details" dialog is showing.
 *
 * The widget itself owns no run data; the per-mode inner components feed it the normalized progress.
 */
export const wizardSyncUiLogic = kea<wizardSyncUiLogicType>([
    path(['scenes', 'onboarding', 'wizardSyncUiLogic']),
    actions({
        dismiss: (key: string) => ({ key }),
        restore: true,
        openDialog: true,
        closeDialog: true,
    }),
    reducers({
        dismissedKey: [
            null as string | null,
            { persist: true },
            {
                dismiss: (_, { key }) => key,
                restore: () => null,
            },
        ],
        dialogOpen: [
            false,
            {
                openDialog: () => true,
                closeDialog: () => false,
                restore: () => false,
            },
        ],
    }),
])
