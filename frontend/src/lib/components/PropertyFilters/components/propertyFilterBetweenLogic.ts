import { actions, kea, key, listeners, path, props, propsChanged, reducers } from 'kea'

import { PropertyFilterBaseValue, PropertyFilterValue } from '~/types'

import type { propertyFilterBetweenLogicType } from './propertyFilterBetweenLogicType'

export interface PropertyFilterBetweenLogicProps {
    key: string
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
}

function parseNumericValue(value: PropertyFilterValue, index: number): number | null {
    if (!Array.isArray(value) || value.length !== 2) {
        return null
    }
    const valueAtIndex = value[index]
    const numValue = Number(valueAtIndex)
    return Number.isNaN(numValue) || valueAtIndex === null ? null : numValue
}

function valuesMatch(a?: PropertyFilterBaseValue, b?: PropertyFilterBaseValue): boolean {
    return Number.isNaN(a) === Number.isNaN(b) ? true : a === b
}

export const propertyFilterBetweenLogic = kea<propertyFilterBetweenLogicType>([
    path(['lib', 'components', 'PropertyFilters', 'components', 'propertyFilterBetweenLogic']),
    props({} as PropertyFilterBetweenLogicProps),
    key((props) => props.key),
    propsChanged(({ actions, props }, oldProps) => {
        const [newMin, newMax] = Array.isArray(props.value) ? props.value : []
        const [oldMin, oldMax] = Array.isArray(oldProps.value) ? oldProps.value : []
        if (!valuesMatch(newMin, oldMin)) {
            actions.setLocalMin(parseNumericValue(props.value, 0))
        }
        if (!valuesMatch(newMax, oldMax)) {
            actions.setLocalMax(parseNumericValue(props.value, 1))
        }
    }),
    actions({
        setLocalMin: (value: number | null) => ({ value }),
        setLocalMax: (value: number | null) => ({ value }),
    }),
    reducers(({ props }) => ({
        localMin: [
            parseNumericValue(props.value, 0),
            {
                setLocalMin: (_, { value }) => value,
            },
        ],
        localMax: [
            parseNumericValue(props.value, 1),
            {
                setLocalMax: (_, { value }) => value,
            },
        ],
    })),
    listeners(({ values, props }) => ({
        setLocalMin: ({ value }) => props.onSet([value ?? NaN, values.localMax ?? NaN]),
        setLocalMax: ({ value }) => props.onSet([values.localMin ?? NaN, value ?? NaN]),
    })),
])
