import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { surveyQuestionLabelsLogic } from 'scenes/surveys/surveyQuestionLabelsLogic'

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
        const suffix = value.replace(/^\$survey_response_/, '')
        if (suffix) {
            // If `surveyQuestionLabelsLogic` is mounted (a `PropertyKeyInfo` for any
            // survey response key triggers the mount, which auto-loads the slim labels
            // endpoint), prefer the actual question text. This branch covers every
            // call site — `PropertyKeyInfo`, the property definitions popover, chart
            // legends, breakdown labels, the admin definitions page — so all of them
            // benefit once the labels have loaded.
            const resolved = surveyQuestionLabelsLogic.findMounted()?.values.surveyQuestionLabels?.[suffix]
            if (resolved) {
                return {
                    label: `${resolved.questionText} · ${resolved.surveyName}`,
                    description: `Response to "${resolved.questionText}" in survey "${resolved.surveyName}".`,
                }
            }
            const parsedIndex = Number(suffix)
            if (Number.isInteger(parsedIndex) && parsedIndex >= 0) {
                const index = parsedIndex + 1
                const ordinal = index === 1 ? 'st' : index === 2 ? 'nd' : index === 3 ? 'rd' : 'th'
                return {
                    label: `Survey response for ${index}${ordinal} question`,
                    description: `The response value for the ${index}${ordinal} question in the survey.`,
                }
            }
            // Modern format `$survey_response_<question-uuid>`, but the labels haven't
            // loaded yet (or this consumer doesn't subscribe so it won't re-render
            // when they do). Emit a generic short-ID label as a placeholder.
            const shortId = suffix.slice(0, 8)
            return {
                label: `Survey response (${shortId}…)`,
                description: `Response for survey question with ID "${suffix}".`,
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

/**
 * Drop definitions flagged `only_shown_on_exact_search` (legacy/deprecated events) from a page
 * of results unless the trimmed query exactly matches the item's name or label. Keeps a fuzzy
 * search like "mcp" from surfacing every retired MCP variant, while typing the full name still
 * finds them. Applied at the data-fetch layer of both TaxonomicFilter variants — the legacy
 * `infiniteListLogic` and the rebuild's `fetchTaxonomicListPage` — so keep the two in sync.
 */
export function filterExactSearchOnlyItems<T>(
    items: T[],
    getName: (item: T) => string | null | undefined,
    type: TaxonomicFilterGroupType,
    searchQuery: string
): T[] {
    const query = searchQuery.trim().toLowerCase()
    return items.filter((item) => {
        const name = getName(item)
        const definition = getCoreFilterDefinition(name, type)
        if (!definition?.only_shown_on_exact_search) {
            return true
        }
        if (!query) {
            return false
        }
        return query === (name ?? '').toString().toLowerCase() || query === definition.label.trim().toLowerCase()
    })
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
