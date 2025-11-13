import { actions, kea, key, listeners, path, props, reducers } from 'kea'

import { PropertyFilterValue } from '~/types'

import type { propertyFilterBetweenLogicType } from './propertyFilterBetweenLogicType'

export interface PropertyFilterBetweenLogicProps {
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
}

function parseNumericValue(value: PropertyFilterValue, index: number): number | null {
    if (!Array.isArray(value) || value.length !== 2) {
        return null
    }
    const valueAtIndex = Array.isArray(value) ? value[index] : null
    const numValue = Number(valueAtIndex)
    return Number.isNaN(numValue) || valueAtIndex === null ? null : numValue
}

export const propertyFilterBetweenLogic = kea<propertyFilterBetweenLogicType>([
    props({} as PropertyFilterBetweenLogicProps),
    key((props) => JSON.stringify(props.value)),
    path(['lib', 'components', 'PropertyFilters', 'components', 'propertyFilterBetweenLogic']),
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
