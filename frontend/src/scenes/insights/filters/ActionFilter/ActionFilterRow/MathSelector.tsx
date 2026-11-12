import { LemonSelect } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'

import { apiValueToMathType } from 'products/product_analytics/frontend/insights/trends/mathsLogic'

import { QuillMathSelector } from './QuillMathSelector'
import type { MathSelectorProps } from './types'
import { useMathSelectorOptions } from './useMathSelectorOptions'

export function MathSelector(props: MathSelectorProps): JSX.Element {
    const options = useMathSelectorOptions(props)
    const quillSurface = useQuillSurface()
    const { math, mathGroupTypeIndex, index, onMathSelect, disabled, disabledReason, size, fullWidth, truncateText } =
        props

    const mathType = apiValueToMathType(math, mathGroupTypeIndex)

    if (quillSurface) {
        return (
            <QuillMathSelector
                section={options[0]}
                value={mathType}
                onSelect={(value) => onMathSelect(index, value)}
                disabled={disabled}
                disabledReason={disabledReason}
                fullWidth={fullWidth}
                data-attr={`math-selector-${index}`}
            />
        )
    }

    return (
        <LemonSelect
            value={mathType}
            options={options}
            onChange={(value) => onMathSelect(index, value)}
            data-attr={`math-selector-${index}`}
            disabled={disabled}
            disabledReason={disabledReason}
            optionTooltipPlacement="right"
            dropdownMatchSelectWidth={false}
            dropdownPlacement="bottom-start"
            size={size}
            fullWidth={fullWidth}
            truncateText={truncateText}
        />
    )
}
