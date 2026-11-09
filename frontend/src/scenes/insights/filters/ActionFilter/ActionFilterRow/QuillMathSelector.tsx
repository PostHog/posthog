import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger, SelectTriggerIcon, cn } from '@posthog/quill'

import { QuillMathOptionItems } from './QuillMathOptionItems'
import type { MathSelectorSection } from './types'

export interface QuillMathSelectorProps {
    section: MathSelectorSection
    value: string
    onSelect: (value: string) => void
    disabled?: boolean
    disabledReason?: string
    fullWidth?: boolean
    'data-attr': string
}

export function QuillMathSelector({
    section,
    value,
    onSelect,
    disabled,
    disabledReason,
    fullWidth,
    'data-attr': dataAttr,
}: QuillMathSelectorProps): JSX.Element {
    const selected = section.options.find((option) => option.value === value)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                disabled={disabled || !!disabledReason}
                render={
                    <Button
                        variant="outline"
                        left
                        disabled={disabled}
                        disabledReason={disabledReason}
                        className={cn('min-w-0 max-w-full', fullWidth && 'w-full')}
                        data-attr={dataAttr}
                    />
                }
            >
                {selected?.icon}
                <span className="min-w-0 flex-1 truncate text-left">{selected?.label ?? value}</span>
                <SelectTriggerIcon />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <QuillMathOptionItems section={section} value={value} onSelect={onSelect} />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
