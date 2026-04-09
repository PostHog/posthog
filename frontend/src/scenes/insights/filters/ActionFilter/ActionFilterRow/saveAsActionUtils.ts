import {
    ActionStepStringMatching,
    ActionStepType,
    AnyPropertyFilter,
    EntityTypes,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { LocalFilter } from '../entityFilterLogic'

interface ElementKeyMapping {
    stepField: 'text' | 'selector' | 'href'
    matchingField: 'text_matching' | 'href_matching' | null
    types: PropertyFilterType[]
    namePrefix: string
    nameQuoted: boolean
}

const ELEMENT_KEY_MAPPINGS: Record<string, ElementKeyMapping> = {
    $el_text: {
        stepField: 'text',
        matchingField: 'text_matching',
        types: [PropertyFilterType.Event, PropertyFilterType.Element],
        namePrefix: '',
        nameQuoted: true,
    },
    text: {
        stepField: 'text',
        matchingField: 'text_matching',
        types: [PropertyFilterType.Event, PropertyFilterType.Element],
        namePrefix: '',
        nameQuoted: true,
    },
    selector: {
        stepField: 'selector',
        matchingField: null,
        types: [PropertyFilterType.Element],
        namePrefix: '',
        nameQuoted: false,
    },
    href: {
        stepField: 'href',
        matchingField: 'href_matching',
        types: [PropertyFilterType.Element],
        namePrefix: 'link ',
        nameQuoted: true,
    },
}

function getMappingForProp(prop: AnyPropertyFilter): ElementKeyMapping | null {
    const key = prop.key ?? ''
    const mapping = ELEMENT_KEY_MAPPINGS[key]
    if (!mapping || !mapping.types.includes(prop.type as PropertyFilterType)) {
        return null
    }
    return mapping
}

function canMapToActionStep(prop: AnyPropertyFilter): boolean {
    const mapping = getMappingForProp(prop)
    if (!mapping) {
        return false
    }
    const operator = 'operator' in prop ? prop.operator : undefined
    const matching = operatorToStringMatching(operator)
    if (mapping.matchingField !== null) {
        return matching !== null
    }
    return matching !== null || operator === undefined
}

export function isAutocaptureFilterWithElements(filter: LocalFilter): boolean {
    if (filter.id !== '$autocapture' || filter.type !== EntityTypes.EVENTS) {
        return false
    }
    return (filter.properties ?? []).some(canMapToActionStep)
}

export function operatorToStringMatching(operator: PropertyOperator | undefined): ActionStepStringMatching | null {
    switch (operator) {
        case PropertyOperator.Exact:
            return 'exact'
        case PropertyOperator.IContains:
            return 'contains'
        case PropertyOperator.Regex:
            return 'regex'
        default:
            return null
    }
}

export function filterToActionStep(filter: LocalFilter): ActionStepType {
    const step: ActionStepType = { event: '$autocapture' }
    const remainingProperties: AnyPropertyFilter[] = []

    for (const prop of filter.properties ?? []) {
        const value = 'value' in prop ? String(prop.value ?? '') : ''
        const operator = 'operator' in prop ? prop.operator : undefined
        const matching = operatorToStringMatching(operator)
        const mapping = getMappingForProp(prop)

        if (mapping && canMapToActionStep(prop) && !step[mapping.stepField]) {
            step[mapping.stepField] = value
            if (mapping.matchingField && matching) {
                step[mapping.matchingField] = matching
            }
        } else {
            remainingProperties.push(prop)
        }
    }

    if (remainingProperties.length > 0) {
        step.properties = remainingProperties
    }

    return step
}

const MAX_NAME_VALUE_LENGTH = 50

function truncate(value: string, maxLength: number): string {
    return value.length > maxLength ? value.slice(0, maxLength) + '…' : value
}

export function generateActionNameFromFilter(filter: LocalFilter): string {
    for (const prop of filter.properties ?? []) {
        const value = 'value' in prop ? String(prop.value ?? '') : ''
        if (!value) {
            continue
        }

        const mapping = getMappingForProp(prop)
        if (mapping) {
            const truncated = truncate(value, MAX_NAME_VALUE_LENGTH)
            return mapping.nameQuoted
                ? `Autocapture: ${mapping.namePrefix}"${truncated}"`
                : `Autocapture: ${mapping.namePrefix}${truncated}`
        }
    }

    return 'Autocapture action'
}
