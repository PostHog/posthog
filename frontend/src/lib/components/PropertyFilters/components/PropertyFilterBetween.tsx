import { useActions, useValues } from 'kea'
// @ts-expect-error - useId exists in React 18 but @types/react is pinned to v17
import { useId } from 'react'

import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { PropertyFilterValue } from '~/types'

import { propertyFilterBetweenLogic } from './propertyFilterBetweenLogic'

export interface PropertyFilterBetweenProps {
    logicKey?: string
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
    size?: 'xsmall' | 'small' | 'medium'
}

const usePropertyFilterBetweenLogic = (
    props: PropertyFilterBetweenProps
): ReturnType<typeof propertyFilterBetweenLogic.build> => {
    const generatedKey = useId()
    const logicKey = props.logicKey || `prop-filter-between-${generatedKey}`
    return propertyFilterBetweenLogic({ ...props, key: logicKey })
}

export function PropertyFilterBetween({ logicKey, value, onSet, size }: PropertyFilterBetweenProps): JSX.Element {
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
