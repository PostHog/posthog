import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonCalendarSelectInput } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { PropertyFilterValue, PropertyType } from '~/types'

import { propertyFilterBetweenLogic } from './propertyFilterBetweenLogic'

export interface PropertyFilterBetweenProps {
    logicKey?: string
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
    size?: 'xsmall' | 'small' | 'medium'
    propertyType?: PropertyType
}

let uniqueMemoizedIndex = 0
const usePropertyFilterBetweenLogic = (
    props: PropertyFilterBetweenProps
): ReturnType<typeof propertyFilterBetweenLogic.build> => {
    const logicKey = useMemo(() => props.logicKey || `prop-filter-between-${uniqueMemoizedIndex++}`, [props.logicKey])
    return propertyFilterBetweenLogic({ ...props, key: logicKey })
}

const dateFormat = 'YYYY-MM-DD'

function DateBetweenInput({
    value,
    onSet,
}: {
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
}): JSX.Element {
    const values = Array.isArray(value) ? value : [null, null]
    const [minOpen, setMinOpen] = useState(false)
    const [maxOpen, setMaxOpen] = useState(false)

    const minValue = values[0] ? dayjs(String(values[0])) : undefined
    const maxValue = values[1] ? dayjs(String(values[1])) : undefined

    return (
        <div className="flex items-center gap-2">
            <LemonCalendarSelectInput
                value={minValue}
                format={dateFormat}
                visible={minOpen}
                placeholder="min date"
                onClickOutside={() => setMinOpen(false)}
                onChange={(date) => {
                    const formatted = date ? date.format(dateFormat) : null
                    onSet([formatted, values[1] ?? null])
                    setMinOpen(false)
                }}
                onClose={() => setMinOpen(false)}
                granularity="day"
                buttonProps={{
                    'data-attr': 'prop-val-min',
                    fullWidth: true,
                    onClick: () => setMinOpen(true),
                }}
            />
            <span className="font-medium">and</span>
            <LemonCalendarSelectInput
                value={maxValue}
                format={dateFormat}
                visible={maxOpen}
                placeholder="max date"
                onClickOutside={() => setMaxOpen(false)}
                onChange={(date) => {
                    const formatted = date ? date.format(dateFormat) : null
                    onSet([values[0] ?? null, formatted])
                    setMaxOpen(false)
                }}
                onClose={() => setMaxOpen(false)}
                granularity="day"
                buttonProps={{
                    'data-attr': 'prop-val-max',
                    fullWidth: true,
                    onClick: () => setMaxOpen(true),
                }}
            />
        </div>
    )
}

function NumericBetweenInput({ logicKey, value, onSet, size }: PropertyFilterBetweenProps): JSX.Element {
    const logic = usePropertyFilterBetweenLogic({ logicKey, value, onSet, size })
    const { localMin, localMax } = useValues(logic)
    const { setLocalMin, setLocalMax } = useActions(logic)

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="number"
                value={localMin ?? undefined}
                data-attr="prop-val-min"
                aria-label="Minimum value"
                onChange={(value) => setLocalMin(value ?? null)}
                placeholder="min"
                size={size}
            />
            <span className="font-medium">and</span>
            <LemonInput
                type="number"
                value={localMax ?? undefined}
                data-attr="prop-val-max"
                aria-label="Maximum value"
                onChange={(value) => setLocalMax(value ?? null)}
                placeholder="max"
                size={size}
            />
        </div>
    )
}

export function PropertyFilterBetween(props: PropertyFilterBetweenProps): JSX.Element {
    if (props.propertyType === PropertyType.DateTime) {
        return <DateBetweenInput value={props.value} onSet={props.onSet} />
    }

    return <NumericBetweenInput {...props} />
}
