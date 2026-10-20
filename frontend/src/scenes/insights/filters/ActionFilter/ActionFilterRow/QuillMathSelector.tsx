import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger, SelectTriggerIcon, cn } from '@posthog/quill'

import { apiValueToMathType } from 'products/product_analytics/frontend/insights/trends/mathsLogic'

import { QuillDisabledReasonTooltip } from './QuillDisabledReasonTooltip'
import { QuillMathMenuItems } from './QuillMathMenuItems'
import type { MathSelectorProps } from './types'
import { flattenMathChoices, useMathSelectorChoices } from './useMathSelectorChoices'

export function QuillMathSelector(props: Omit<MathSelectorProps, 'size' | 'style' | 'truncateText'>): JSX.Element {
    const { math, mathGroupTypeIndex, index, onMathSelect, disabled, disabledReason, fullWidth } = props
    const choices = useMathSelectorChoices(props)
    const mathType = apiValueToMathType(math, mathGroupTypeIndex)
    const selected = flattenMathChoices(choices.entries).find((choice) => choice.value === mathType)

    const trigger = (
        <Button
            variant="outline"
            left
            disabled={disabled || !!disabledReason}
            data-attr={`math-selector-${index}`}
            className={cn('min-w-0 max-w-full', fullWidth && 'w-full')}
        >
            <span className="min-w-0 flex-1 truncate text-start">{selected?.label ?? mathType}</span>
            <SelectTriggerIcon />
        </Button>
    )

    if (disabledReason) {
        return <QuillDisabledReasonTooltip reason={disabledReason}>{trigger}</QuillDisabledReasonTooltip>
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={trigger} />
            <DropdownMenuContent align="start" className="w-max min-w-48 max-w-80">
                <QuillMathMenuItems
                    choices={choices}
                    value={mathType}
                    onChange={(value) => onMathSelect(index, value)}
                    disabled={disabled}
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
