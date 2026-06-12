import { truncate } from 'lib/utils'

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
    if (mapping.matchingField !== null) {
        return operatorToStringMatching(operator) !== null
    }
    return operator === undefined || operator === PropertyOperator.Exact
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

function isMultiValue(prop: AnyPropertyFilter): boolean {
    return 'value' in prop && Array.isArray(prop.value) && prop.value.length > 1
}

function extractStringValue(prop: AnyPropertyFilter): string {
    if (!('value' in prop) || prop.value == null) {
        return ''
    }
    const raw = prop.value
    return Array.isArray(raw) ? String(raw[0] ?? '') : String(raw)
}

export function filterToActionStep(filter: LocalFilter): ActionStepType {
    const step: ActionStepType = { event: '$autocapture' }
    const remainingProperties: AnyPropertyFilter[] = []

    for (const prop of filter.properties ?? []) {
        const value = extractStringValue(prop)
        const operator = 'operator' in prop ? prop.operator : undefined
        const matching = operatorToStringMatching(operator)
        const mapping = getMappingForProp(prop)

        if (mapping && canMapToActionStep(prop) && !isMultiValue(prop) && !step[mapping.stepField]) {
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

export function generateActionNameFromFilter(filter: LocalFilter): string {
    for (const prop of filter.properties ?? []) {
        if (!canMapToActionStep(prop)) {
            continue
        }
        const value = extractStringValue(prop)
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
