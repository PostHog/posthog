import { actions, kea, reducers, path, key, props, connect, selectors } from 'kea'

import type { manualReleaseLogicType } from './manualReleaseLogicType'
import { featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagGroupType, FeatureFlagType } from '~/types'

export interface ManualReleaseLogicProps {
    id: number
}

export const hasManualReleaseCondition = (featureFlag: FeatureFlagType, group: FeatureFlagGroupType): boolean => {
    return !!group.properties.some((property) => property.key === '$feature_enrollment/' + featureFlag.key)
}

export const manualReleaseLogic = kea<manualReleaseLogicType>([
    path(['scenes', 'feature-flags', 'manualReleaseLogic']),
    props({} as ManualReleaseLogicProps),
    key(({ id }) => id ?? 'unknown'),
    connect((props: ManualReleaseLogicProps) => ({
        actions: [featureFlagLogic({ id: props.id }), ['enableManualCondition']],
        values: [featureFlagLogic({ id: props.id }), ['featureFlag']],
    })),
    actions({
        toggleImplementOptInInstructionsModal: true,
        toggleEnrollmentModal: true,
    }),
    reducers({
        implementOptInInstructionsModal: [
            false,
            {
                toggleImplementOptInInstructionsModal: (state) => !state,
            },
        ],
        enrollmentModal: [
            false,
            {
                toggleEnrollmentModal: (state) => !state,
            },
        ],
    }),
    selectors({
        hasManualRelease: [
            (s) => [s.featureFlag],
            (featureFlag: FeatureFlagType): boolean => {
                return featureFlag.filters.groups.some((group) => hasManualReleaseCondition(featureFlag, group))
            },
        ],
        manualReleasePropKey: [
            (s) => [s.featureFlag],
            (featureFlag: FeatureFlagType): string => {
                return '$feature_enrollment/' + featureFlag.key
            },
        ],
    }),
])
