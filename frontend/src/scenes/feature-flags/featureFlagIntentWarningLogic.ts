import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS, INSTANTLY_AVAILABLE_PROPERTIES } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'

import { cohortsModel } from '~/models/cohortsModel'
import {
    CohortCriteriaGroupFilter,
    CohortType,
    FeatureFlagGroupType,
    FeatureFlagType,
    PropertyFilterType,
} from '~/types'

import type { featureFlagIntentWarningLogicType } from './featureFlagIntentWarningLogicType'
import { featureFlagLogic, FeatureFlagLogicProps } from './featureFlagLogic'

export type FlagIntent = 'local-eval' | 'first-page-load'

function hasBehavioralCriteria(cohort: CohortType): boolean {
    const values = cohort.filters?.properties?.values
    if (!values) {
        return false
    }
    return values.some((value) => {
        if ('values' in value) {
            const nested = value as CohortCriteriaGroupFilter
            return nested.values.some((v) => 'type' in v && v.type === BehavioralFilterKey.Behavioral)
        }
        return 'type' in value && value.type === BehavioralFilterKey.Behavioral
    })
}

function isGroupBroad(group: FeatureFlagGroupType): boolean {
    const hasNoProperties = !group.properties || group.properties.length === 0
    const isFullRollout =
        group.rollout_percentage === null || group.rollout_percentage === undefined || group.rollout_percentage === 100
    return hasNoProperties && isFullRollout
}

export const featureFlagIntentWarningLogic = kea<featureFlagIntentWarningLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagIntentWarningLogic']),
    props({} as FeatureFlagLogicProps),
    key(({ id }) => id ?? 'unknown'),
    connect((props: FeatureFlagLogicProps) => ({
        values: [
            featureFlagLogic(props),
            ['featureFlag', 'flagIntent'],
            cohortsModel,
            ['cohortsById'],
            enabledFeaturesLogic,
            ['featureFlags as enabledFeatures'],
        ],
    })),

    actions({
        toggleIssuesExpanded: true,
    }),

    reducers({
        issuesExpanded: [
            false,
            {
                toggleIssuesExpanded: (expanded) => !expanded,
            },
        ],
    }),

    selectors({
        unreachableGroups: [
            (s) => [s.featureFlag],
            (featureFlag: FeatureFlagType): Set<number> => {
                const groups = featureFlag?.filters?.groups
                if (!groups || groups.length <= 1) {
                    return new Set()
                }

                const unreachable = new Set<number>()
                let foundBroad = false
                for (let i = 0; i < groups.length; i++) {
                    if (foundBroad) {
                        unreachable.add(i)
                    } else if (isGroupBroad(groups[i])) {
                        foundBroad = true
                    }
                }
                return unreachable
            },
        ],

        intentIssues: [
            (s) => [s.featureFlag, s.flagIntent, s.cohortsById, s.enabledFeatures],
            (
                featureFlag: FeatureFlagType,
                flagIntent: FlagIntent | null,
                cohortsById: Partial<Record<string | number, CohortType>>,
                enabledFeatures: Record<string, boolean | string>
            ): string[] => {
                const intentsEnabled = !!enabledFeatures[FEATURE_FLAGS.FEATURE_FLAG_CREATION_INTENTS]
                if (!intentsEnabled || !flagIntent) {
                    return []
                }

                const groups = featureFlag?.filters?.groups
                if (!groups) {
                    return []
                }

                const issues = new Set<string>()

                if (flagIntent === 'local-eval') {
                    if (featureFlag?.ensure_experience_continuity) {
                        issues.add(
                            'Persist across authentication requires server-side state that local evaluation cannot access'
                        )
                    }

                    for (const group of groups) {
                        for (const property of group.properties || []) {
                            if (property.type === PropertyFilterType.Cohort) {
                                // cohortId may be numeric or stringified depending on filter source
                                const cohortId = property.value
                                const cohort = cohortsById[cohortId] ?? cohortsById[String(cohortId)]
                                if (cohort?.is_static) {
                                    issues.add('Static cohorts are not sent to SDKs')
                                } else if (cohort && hasBehavioralCriteria(cohort)) {
                                    issues.add('Behavioral cohorts cannot be evaluated locally')
                                }
                            }

                            if (isPropertyFilterWithOperator(property) && property.operator === 'is_not_set') {
                                issues.add(
                                    '"is not set" can\'t be evaluated locally because SDKs only receive properties you send, not the full list'
                                )
                            }
                        }
                    }
                }

                if (flagIntent === 'first-page-load') {
                    const allSlowKeys = new Set<string>()
                    let hasCohort = false

                    for (const group of groups) {
                        for (const property of group.properties || []) {
                            if (property.type === PropertyFilterType.Cohort) {
                                hasCohort = true
                            } else if (property.key && !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key)) {
                                allSlowKeys.add(property.key)
                            }
                        }
                    }

                    if (allSlowKeys.size === 1) {
                        const key = [...allSlowKeys][0]
                        issues.add(`The property "${key}" won't be available on first page load and can cause flicker`)
                    } else if (allSlowKeys.size > 1) {
                        issues.add(
                            `${allSlowKeys.size} properties won't be available on first page load and can cause flicker`
                        )
                    }
                    if (hasCohort) {
                        issues.add('Cohort membership is not available on first page load and can cause flicker')
                    }
                }

                return [...issues]
            },
        ],
    }),
])
