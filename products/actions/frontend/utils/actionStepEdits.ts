import {
    ActionStepStringMatching,
    ActionStepType,
    AnyPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { SCREEN_NAME_PROPERTY, type ScreenNameMatching, isScreenNameFilter } from './screenName'

export const ACTION_STEP_MATCHING_LABEL: Record<ActionStepStringMatching, string> = {
    exact: 'matches exactly',
    regex: 'matches regex',
    contains: 'contains',
}

export type ActionStepTypeOption = '$pageview' | '$autocapture' | '$screen' | 'event'
export type ActionStepOptionField = keyof Pick<ActionStepType, 'href' | 'text' | 'selector' | 'url' | 'tag_name'>
export type ActionStepMatchingField = 'url' | 'text' | 'href'

export function withoutActionStep(steps: ActionStepType[], index: number): ActionStepType[] {
    return steps.filter((_, stepIndex) => stepIndex !== index)
}

export function withActionStepAt(steps: ActionStepType[], index: number, step: ActionStepType): ActionStepType[] {
    return steps.map((existing, stepIndex) => (stepIndex === index ? step : existing))
}

/** The match group type the step is set to, or undefined before the person picks one. */
export function actionStepTypeOption(step: ActionStepType): ActionStepTypeOption | undefined {
    if (step.event === undefined) {
        return undefined
    }
    return step.event === '$autocapture' || step.event === '$pageview' || step.event === '$screen'
        ? step.event
        : 'event'
}

/** The step with its match group type switched, clearing the fields the new type does not use. */
export function withActionStepType(step: ActionStepType, type: string): ActionStepType | null {
    const overrides: Record<string, Partial<ActionStepType>> = {
        $autocapture: { event: '$autocapture' },
        event: { event: null },
        $pageview: { event: '$pageview' },
        $screen: { event: '$screen', url: null, url_matching: null },
    }
    return type in overrides ? { ...step, ...overrides[type] } : null
}

export function withActionStepOption(
    step: ActionStepType,
    field: ActionStepOptionField,
    value: string
): ActionStepType {
    // An empty string is a valid filter value that only matches empty values, so an emptied input clears the field.
    return { ...step, [field]: value || null }
}

export function actionStepMatching(step: ActionStepType, field: ActionStepMatchingField): ActionStepStringMatching {
    const value = step[`${field}_matching`] as ActionStepStringMatching | null | undefined
    return value || (field === 'url' ? 'contains' : 'exact')
}

export function withActionStepMatching(
    step: ActionStepType,
    field: ActionStepMatchingField,
    matching: string
): ActionStepType {
    return { ...step, [`${field}_matching`]: matching }
}

/** The step's property filters other than the screen name, which has a field of its own. */
export function actionStepFilters(step: ActionStepType): AnyPropertyFilter[] | undefined {
    return step.event === '$screen' ? step.properties?.filter((p) => !isScreenNameFilter(p)) : step.properties
}

export function withActionStepFilters(step: ActionStepType, properties: AnyPropertyFilter[]): ActionStepType {
    const screenNameFilter =
        step.event === '$screen' ? (step.properties?.filter((p) => isScreenNameFilter(p)) ?? []) : []
    return { ...step, properties: [...screenNameFilter, ...properties] }
}

export function actionStepScreenNames(step: ActionStepType): {
    screenNames: string[]
    operator: ScreenNameMatching | undefined
} {
    const existingFilter = step.properties?.find(isScreenNameFilter)
    const rawValue = existingFilter && 'value' in existingFilter ? existingFilter.value : undefined
    const screenNames: string[] =
        rawValue == null || rawValue === '' ? [] : Array.isArray(rawValue) ? rawValue.map(String) : [String(rawValue)]
    const operator =
        existingFilter && 'operator' in existingFilter ? (existingFilter.operator as ScreenNameMatching) : undefined
    return { screenNames, operator }
}

export function withActionStepScreenName(
    step: ActionStepType,
    value: string | string[],
    operator: ScreenNameMatching
): ActionStepType {
    const otherProperties = (step.properties || []).filter((p) => !isScreenNameFilter(p))
    const isEmpty = Array.isArray(value) ? value.length === 0 : !value
    if (isEmpty) {
        return { ...step, properties: otherProperties }
    }
    return {
        ...step,
        properties: [
            ...otherProperties,
            {
                key: SCREEN_NAME_PROPERTY,
                value,
                operator: operator as PropertyOperator,
                type: PropertyFilterType.Event,
            },
        ],
    }
}
