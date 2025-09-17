import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { CoreFilterDefinition } from '~/types'

import { CORE_FILTER_DEFINITIONS_BY_GROUP } from './taxonomy'

/** Return whether a given filter key is part of PostHog's core (marked by the PostHog logo). */

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
    if (type in CORE_FILTER_DEFINITIONS_BY_GROUP && value in CORE_FILTER_DEFINITIONS_BY_GROUP[type]) {
        return { ...CORE_FILTER_DEFINITIONS_BY_GROUP[type][value] }
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
        const surveyIndex = value.replace(/^\$survey_response_/, '')
        if (surveyIndex) {
            const index = Number(surveyIndex) + 1
            // yes this will return 21th, but I'm applying the domain logic of
            // it being very unlikely that someone will have more than 20 questions,
            // rather than hyper optimising the suffix.
            const suffix = index === 1 ? 'st' : index === 2 ? 'nd' : index === 3 ? 'rd' : 'th'
            return {
                label: `Survey Response Question ID: ${surveyIndex}`,
                description: `The response value for the ${index}${suffix} question in the survey.`,
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
    for (const type of Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP) as TaxonomicFilterGroupType[]) {
        if (propertyKey in CORE_FILTER_DEFINITIONS_BY_GROUP[type]) {
            return type
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
    const group = CORE_FILTER_DEFINITIONS_BY_GROUP[type]
    if (group) {
        const foundKey = Object.entries(group).find(([_, def]) => (def as any).label === value || _ === value)?.[0]
        return foundKey || value
    }
    return value
}
