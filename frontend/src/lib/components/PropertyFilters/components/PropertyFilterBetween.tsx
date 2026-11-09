import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { NumberFieldGroup, NumberFieldInput, NumberFieldRoot } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { PropertyFilterValue } from '~/types'

import { propertyFilterBetweenLogic } from './propertyFilterBetweenLogic'

export interface PropertyFilterBetweenProps {
    logicKey?: string
    value: PropertyFilterValue
    onSet: (newValue: PropertyFilterValue) => void
    size?: 'xsmall' | 'small' | 'medium'
}

const RAW_NUMBER_FORMAT: Intl.NumberFormatOptions = { useGrouping: false, maximumFractionDigits: 20 }

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
    const quillSurface = useQuillSurface()

    if (quillSurface) {
        return (
            <div className="flex items-center gap-2">
                <NumberFieldRoot
                    className="min-w-0 flex-1"
                    value={localMin}
                    onValueChange={(next: number | null) => setLocalMin(next)}
                    format={RAW_NUMBER_FORMAT}
                    allowOutOfRange
                >
                    <NumberFieldGroup>
                        <NumberFieldInput data-attr="prop-val-min" aria-label="Minimum value" placeholder="min" />
                    </NumberFieldGroup>
                </NumberFieldRoot>
                <span className="font-medium">and</span>
                <NumberFieldRoot
                    className="min-w-0 flex-1"
                    value={localMax}
                    onValueChange={(next: number | null) => setLocalMax(next)}
                    format={RAW_NUMBER_FORMAT}
                    allowOutOfRange
                >
                    <NumberFieldGroup>
                        <NumberFieldInput data-attr="prop-val-max" aria-label="Maximum value" placeholder="max" />
                    </NumberFieldGroup>
                </NumberFieldRoot>
            </div>
        )
    }

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
