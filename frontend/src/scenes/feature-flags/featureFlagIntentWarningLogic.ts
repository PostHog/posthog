import { connect, kea, key, path, props, selectors } from 'kea'

import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS, INSTANTLY_AVAILABLE_PROPERTIES } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { AnyPropertyFilter, CohortType, FeatureFlagGroupType, FeatureFlagType, PropertyFilterType } from '~/types'

import type { featureFlagIntentWarningLogicType } from './featureFlagIntentWarningLogicType'
import { featureFlagLogic, FeatureFlagLogicProps } from './featureFlagLogic'

export type FlagIntent = 'local-eval' | 'first-page-load'

export interface ConditionWarning {
    type:
        | 'static_cohort'
        | 'non_static_cohort'
        | 'is_not_set'
        | 'regex_unsupported'
        | 'flicker_risk'
        | 'unreachable_condition'
    severity: 'warning' | 'info'
    title: string
    description: string
    docUrl?: string
}

const REGEX_LOOKAHEAD = /(?<!\\)\(\?[=!]/
const REGEX_LOOKBEHIND = /(?<!\\)\(\?<[=!]/
const REGEX_BACKREFERENCE = /(?<!\\)\\[1-9]/

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

    selectors({
        unreachableGroups: [
            (s) => [s.featureFlag],
            (featureFlag: FeatureFlagType): Set<number> => {
                const groups = featureFlag?.filters?.groups
                if (!groups || groups.length <= 1) {
                    return new Set()
                }

                const unreachable = new Set<number>()
                for (let i = 1; i < groups.length; i++) {
                    // If any prior group is broad (no filters + 100% rollout),
                    // all subsequent groups are unreachable
                    const hasBroadPrior = groups.slice(0, i).some(isGroupBroad)
                    if (hasBroadPrior) {
                        unreachable.add(i)
                    }
                }
                return unreachable
            },
        ],

        warningsByGroup: [
            (s) => [s.featureFlag, s.flagIntent, s.cohortsById, s.enabledFeatures, s.unreachableGroups],
            (
                featureFlag: FeatureFlagType,
                flagIntent: FlagIntent | null,
                cohortsById: Partial<Record<string | number, CohortType>>,
                enabledFeatures: Record<string, boolean | string>,
                unreachableGroups: Set<number>
            ): Record<number, ConditionWarning[]> => {
                const groups = featureFlag?.filters?.groups
                if (!groups) {
                    return {}
                }

                const intentsEnabled = !!enabledFeatures[FEATURE_FLAGS.FEATURE_FLAG_CREATION_INTENTS]
                const result: Record<number, ConditionWarning[]> = {}

                groups.forEach((group: FeatureFlagGroupType, index: number) => {
                    const warnings: ConditionWarning[] = []

                    // Unreachable conditions (always-on, no feature flag gate)
                    if (unreachableGroups.has(index)) {
                        warnings.push({
                            type: 'unreachable_condition',
                            severity: 'warning',
                            title: 'Unreachable condition',
                            description:
                                'A previous condition matches all users at 100% rollout, so this condition will never be evaluated.',
                        })
                    }

                    // Intent-specific warnings (gated behind feature flag)
                    if (intentsEnabled && flagIntent) {
                        const properties = group.properties || []

                        if (flagIntent === 'local-eval') {
                            let hasStaticCohort = false
                            let hasNonStaticCohort = false
                            const isNotSetKeys: string[] = []
                            const unsupportedRegexKeys: string[] = []

                            properties.forEach((property: AnyPropertyFilter) => {
                                if (property.type === PropertyFilterType.Cohort) {
                                    const cohortId = property.value
                                    const cohort = cohortsById[cohortId] ?? cohortsById[String(cohortId)]
                                    if (cohort?.is_static) {
                                        hasStaticCohort = true
                                    } else {
                                        hasNonStaticCohort = true
                                    }
                                }

                                if (isPropertyFilterWithOperator(property) && property.operator === 'is_not_set') {
                                    isNotSetKeys.push(property.key)
                                }

                                if (isPropertyFilterWithOperator(property) && property.operator === 'regex') {
                                    const pattern = String(property.value)
                                    if (
                                        REGEX_LOOKAHEAD.test(pattern) ||
                                        REGEX_LOOKBEHIND.test(pattern) ||
                                        REGEX_BACKREFERENCE.test(pattern)
                                    ) {
                                        unsupportedRegexKeys.push(property.key)
                                    }
                                }
                            })

                            if (hasStaticCohort) {
                                warnings.push({
                                    type: 'static_cohort',
                                    severity: 'warning',
                                    title: 'Static cohort not supported for local evaluation',
                                    description:
                                        'Static cohorts cannot be evaluated locally because the full membership list is not sent to SDKs. Use a dynamic cohort with property filters instead.',
                                    docUrl: 'https://posthog.com/docs/feature-flags/local-evaluation',
                                })
                            }

                            if (hasNonStaticCohort) {
                                warnings.push({
                                    type: 'non_static_cohort',
                                    severity: 'warning',
                                    title: 'Behavioral cohort may prevent local evaluation',
                                    description:
                                        'Cohorts using behavioral filters (events, sequences) cannot be evaluated locally. Only cohorts with person/group property filters support local evaluation.',
                                    docUrl: 'https://posthog.com/docs/feature-flags/local-evaluation',
                                })
                            }

                            if (isNotSetKeys.length > 0) {
                                warnings.push({
                                    type: 'is_not_set',
                                    severity: 'warning',
                                    title: '"is not set" operator not supported for local evaluation',
                                    description:
                                        'The "is not set" operator requires knowledge of all person properties, which may not be available during local evaluation. Consider using explicit property values instead.',
                                    docUrl: 'https://posthog.com/docs/feature-flags/local-evaluation',
                                })
                            }

                            if (unsupportedRegexKeys.length > 0) {
                                warnings.push({
                                    type: 'regex_unsupported',
                                    severity: 'warning',
                                    title: 'Regex feature not supported for local evaluation',
                                    description:
                                        'Lookaheads, lookbehinds, and backreferences are not supported by all SDK regex engines. Use simpler regex patterns for reliable local evaluation.',
                                    docUrl: 'https://posthog.com/docs/feature-flags/local-evaluation',
                                })
                            }
                        }

                        if (flagIntent === 'first-page-load') {
                            const flickerIssues: string[] = []

                            properties.forEach((property: AnyPropertyFilter) => {
                                if (property.type === PropertyFilterType.Cohort) {
                                    flickerIssues.push('Cohort filters are resolved server-side')
                                } else if (property.key && !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key)) {
                                    flickerIssues.push(
                                        `"${property.key}" isn't available until after the first network request`
                                    )
                                }
                            })

                            if (flickerIssues.length > 0) {
                                warnings.push({
                                    type: 'flicker_risk',
                                    severity: 'info',
                                    title: 'These conditions can cause flicker',
                                    description:
                                        flickerIssues.join('. ') +
                                        '. Until the data loads, the flag evaluates to false, which can cause content to flicker. Use bootstrapping to provide the correct flag value immediately.',
                                    docUrl: 'https://posthog.com/docs/feature-flags/bootstrapping',
                                })
                            }
                        }
                    }

                    if (warnings.length > 0) {
                        result[index] = warnings
                    }
                })

                return result
            },
        ],
    }),
])
