import { DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger } from '@posthog/quill'

import { apiValueToMathType } from 'products/product_analytics/frontend/insights/trends/mathsLogic'

import { QuillMathOptionItems } from './QuillMathOptionItems'
import type { MathSelectorProps } from './types'
import { useMathSelectorOptions } from './useMathSelectorOptions'

export function QuillMathSubMenu(props: MathSelectorProps): JSX.Element {
    const [section] = useMathSelectorOptions(props)
    const { math, mathGroupTypeIndex, index, onMathSelect } = props
    const mathType = apiValueToMathType(math, mathGroupTypeIndex)
    const selected = section.options.find((option) => option.value === mathType)

    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger data-attr={`math-selector-${index}`}>
                {selected?.icon}
                {selected?.label ?? mathType}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                <QuillMathOptionItems
                    section={section}
                    value={mathType}
                    onSelect={(value) => onMathSelect(index, value)}
                />
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
