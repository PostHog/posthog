import { connect, kea, key, path, props, selectors } from 'kea'

import { evaluateDetections } from '~/lib/components/HogSense'
import type { Finding } from '~/lib/components/HogSense'
import { cohortsModel } from '~/models/cohortsModel'
import { CohortType, FeatureFlagType } from '~/types'

import type { featureFlagDetectionLogicType } from './featureFlagDetectionLogicType'
import { featureFlagDetections } from './featureFlagDetections'
import { featureFlagLogic } from './featureFlagLogic'

export interface FeatureFlagDetectionLogicProps {
    id: number | 'new' | 'link'
}

export const featureFlagDetectionLogic = kea<featureFlagDetectionLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagDetectionLogic']),
    props({} as FeatureFlagDetectionLogicProps),
    key(({ id }) => id ?? 'unknown'),

    connect(({ id }: FeatureFlagDetectionLogicProps) => ({
        values: [featureFlagLogic({ id }), ['featureFlag'], cohortsModel, ['cohortsById']],
    })),

    selectors({
        findings: [
            (s) => [s.featureFlag, s.cohortsById],
            (featureFlag: FeatureFlagType, cohortsById: Partial<Record<string | number, CohortType>>): Finding[] => {
                if (!featureFlag) {
                    return []
                }
                const context = { ...featureFlag, _cohortsById: cohortsById }
                return evaluateDetections(featureFlagDetections, context, {
                    entityType: 'feature_flag',
                    entityId: featureFlag.id ?? undefined,
                })
            },
        ],
    }),
])
