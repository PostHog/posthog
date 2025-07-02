import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { FeatureFlagType } from '~/types'
import { openConfirmationModal } from './ConfirmationModal'

import type { featureFlagConfirmationLogicType } from './featureFlagConfirmationLogicType'

export interface FeatureFlagConfirmationLogicProps {
    featureFlag: FeatureFlagType
    onConfirm: () => void
}

export const featureFlagConfirmationLogic = kea<featureFlagConfirmationLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagConfirmationLogic']),
    props({} as FeatureFlagConfirmationLogicProps),
    key(({ featureFlag }) => featureFlag.id ?? 'new'),
    actions(() => ({
        setFlagChanges: true,
        showConfirmationModal: true,
        confirmChanges: true,
    })),
    reducers({
        flagChanges: [
            [] as string[],
            {
                setFlagChanges: (_, { changes }: { changes: string[] }) => changes,
            },
        ],
        showSaveConfirmModal: [
            false,
            {
                showConfirmationModal: (_, { show }: { show: boolean }) => show,
            },
        ],
    }),
    selectors({
        hasChanges: [(s) => [s.flagChanges], (changes: string[]) => changes.length > 0],
    }),
    listeners(({ values, props }) => ({
        confirmChanges: () => {
            if (values.hasChanges) {
                openConfirmationModal({
                    featureFlag: props.featureFlag,
                    type: 'multi-changes',
                    changes: values.flagChanges,
                    onConfirm: props.onConfirm,
                })
            } else {
                props.onConfirm()
            }
        },
    })),
])
