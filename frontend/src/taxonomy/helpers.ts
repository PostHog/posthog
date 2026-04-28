import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { CoreFilterDefinition } from '~/types'

import { CORE_FILTER_DEFINITIONS_BY_GROUP, CoreFilterDefinitionsGroup } from './taxonomy'

/** Return whether a given filter key is part of PostHog's core (marked by the PostHog logo). */

const hasCoreFilterDefinitionsForGroup = (
    type: TaxonomicFilterGroupType
): Record<string, CoreFilterDefinition> | null =>
    type in CORE_FILTER_DEFINITIONS_BY_GROUP
        ? CORE_FILTER_DEFINITIONS_BY_GROUP[type as CoreFilterDefinitionsGroup]
        : null

export function isCoreFilter(key: string): boolean {
    return Object.values(CORE_FILTER_DEFINITIONS_BY_GROUP).some((mapping) => Object.keys(mapping).includes(key))
}

export type PropertyKey = string | null | undefined

export function getCoreFilterDefinition(
    value: string | null | undefined,
    type: TaxonomicFilterGroupType
): CoreFilterDefinition | null {
    if (value == undefined) {
        return null
    }

    value = value.toString()
    const isGroupTaxonomicFilterType = type.startsWith('groups_')
    const groupDefinitions = hasCoreFilterDefinitionsForGroup(type)
    if (groupDefinitions && value in groupDefinitions) {
        return { ...groupDefinitions[value] }
    } else if (
        isGroupTaxonomicFilterType &&
        value in CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.GroupsPrefix]
    ) {
        return { ...CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.GroupsPrefix][value] }
    } else if (value.startsWith('$survey_responded/')) {
        const surveyId = value.replace(/^\$survey_responded\//, '')
        if (surveyId) {
            return {
                label: `Survey Responded: ${surveyId}`,
                description: `Whether the user responded to survey with ID: "${surveyId}".`,
            }
        }
    } else if (value.startsWith('$survey_dismissed/')) {
        const surveyId = value.replace(/^\$survey_dismissed\//, '')
        if (surveyId) {
            return {
                label: `Survey Dismissed: ${surveyId}`,
                description: `Whether the user dismissed survey with ID: "${surveyId}".`,
            }
        }
    } else if (value.startsWith('$survey_response_')) {
        const surveyIndexOrId = value.replace(/^\$survey_response_/, '')
        if (surveyIndexOrId) {
            // Two key formats exist:
            //   - index-based: `$survey_response_<n>` where n is 0-based question index
            //   - id-based:    `$survey_response_<question_uuid>` (stable across reorders/deletions)
            const numericIndex = Number(surveyIndexOrId)
            if (!Number.isNaN(numericIndex)) {
                const oneBasedIndex = numericIndex + 1
                const lastTwo = oneBasedIndex % 100
                const lastOne = oneBasedIndex % 10
                const suffix =
                    lastTwo >= 11 && lastTwo <= 13
                        ? 'th'
                        : lastOne === 1
                            ? 'st'
                            : lastOne === 2
                                ? 'nd'
                                : lastOne === 3
                                    ? 'rd'
                                    : 'th'
                return {
                    label: `Survey response for ${oneBasedIndex}${suffix} question`,
                    description: `The response value for the ${oneBasedIndex}${suffix} question in the survey.`,
                }
            }
            // Non-numeric — treat as an id-based response key. We cannot resolve the
            // question text without the survey context, so surface the id instead.
            return {
                label: `Survey response for question ${surveyIndexOrId}`,
                description: `The response value for the survey question with id "${surveyIndexOrId}". This key is stable across question reorders and deletions.`,
            }
        }
    } else if (value.startsWith('$feature/')) {
        const featureFlagKey = value.replace(/^\$feature\//, '')
        if (featureFlagKey) {
            return {
                label: `Feature: ${featureFlagKey}`,
                description: `Value for the feature flag "${featureFlagKey}" when this event was sent.`,
                examples: ['true', 'variant-1a'],
            }
        }
    } else if (value.startsWith('$feature_enrollment/')) {
        const featureFlagKey = value.replace(/^\$feature_enrollment\//, '')
        if (featureFlagKey) {
            return {
                label: `Feature Enrollment: ${featureFlagKey}`,
                description: `Whether the user has opted into the "${featureFlagKey}" beta program.`,
                examples: ['true', 'false'],
            }
        }
    } else if (value.startsWith('$feature_interaction/')) {
        const featureFlagKey = value.replace(/^\$feature_interaction\//, '')
        if (featureFlagKey) {
            return {
                label: `Feature Interaction: ${featureFlagKey}`,
                description: `Whether the user has interacted with "${featureFlagKey}".`,
                examples: ['true', 'false'],
            }
        }
    }
    return null
}

export function getFirstFilterTypeFor(propertyKey: string): TaxonomicFilterGroupType | null {
    for (const type of Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP) as CoreFilterDefinitionsGroup[]) {
        if (propertyKey in CORE_FILTER_DEFINITIONS_BY_GROUP[type]) {
            return type as TaxonomicFilterGroupType
        }
    }
    return null
}

export function getFilterLabel(key: PropertyKey, type: TaxonomicFilterGroupType): string {
    const data = getCoreFilterDefinition(key, type)
    return (data ? data.label : key)?.trim() ?? '(empty string)'
}

export function getPropertyKey(value: string, type: TaxonomicFilterGroupType): string {
    // Find the key by looking through the mapping
    const group = hasCoreFilterDefinitionsForGroup(type)
    if (group) {
        const foundKey = Object.entries(group).find(([_, def]) => (def as any).label === value || _ === value)?.[0]
        return foundKey || value
    }
    return value
}
