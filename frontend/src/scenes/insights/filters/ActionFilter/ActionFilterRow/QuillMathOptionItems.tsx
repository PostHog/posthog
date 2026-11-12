import {
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    Text,
} from '@posthog/quill'

import { resolveTooltipTitle } from 'lib/lemon-ui/Tooltip/resolveTooltipTitle'

import type { MathSelectorSection } from './types'

export interface QuillMathOptionItemsProps {
    section: MathSelectorSection
    value: string
    onSelect: (value: string) => void
}

export function QuillMathOptionItems({ section, value, onSelect }: QuillMathOptionItemsProps): JSX.Element {
    return (
        <>
            <DropdownMenuRadioGroup value={value} onValueChange={(next) => onSelect(next as string)}>
                {section.options.map((option) =>
                    option.choice ? (
                        <DropdownMenuSub key={option.choice.prefix}>
                            <DropdownMenuSubTrigger
                                inset
                                disabledReason={option.disabledReason}
                                data-attr={option['data-attr']}
                            >
                                {option.icon}
                                {option.choice.prefix}
                                {option.value === value && (
                                    <Text size="xs" variant="muted" render={<span className="ms-auto ps-4" />}>
                                        {option.choice.options.find((sub) => sub.value === option.choice?.value)
                                            ?.label ?? option.choice.value}
                                    </Text>
                                )}
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                {/* A tooltip beside the trigger would open over this submenu, so the help sits at its top. */}
                                {option.tooltip && (
                                    <>
                                        <Text
                                            size="xs"
                                            variant="muted"
                                            render={<div className="max-w-64 px-2 py-1.5" />}
                                        >
                                            {resolveTooltipTitle(option.tooltip)}
                                        </Text>
                                        <DropdownMenuSeparator />
                                    </>
                                )}
                                <DropdownMenuRadioGroup
                                    value={option.value === value ? option.choice.value : null}
                                    onValueChange={(next) => option.choice?.onSelect(next as string)}
                                >
                                    {option.choice.options.map((sub) => (
                                        <DropdownMenuRadioItem
                                            key={sub.value}
                                            value={sub.value}
                                            closeOnClick
                                            tooltip={resolveTooltipTitle(sub.tooltip)}
                                            disabledReason={sub.disabledReason}
                                            data-attr={sub['data-attr']}
                                        >
                                            {sub.label}
                                        </DropdownMenuRadioItem>
                                    ))}
                                </DropdownMenuRadioGroup>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    ) : (
                        <DropdownMenuRadioItem
                            key={option.value}
                            value={option.value}
                            closeOnClick
                            tooltip={resolveTooltipTitle(option.tooltip)}
                            disabledReason={option.disabledReason}
                            data-attr={option['data-attr']}
                        >
                            {option.icon}
                            {option.label}
                        </DropdownMenuRadioItem>
                    )
                )}
            </DropdownMenuRadioGroup>
            {section.footer && (
                <>
                    <DropdownMenuSeparator />
                    <div data-not-quill className="px-2 py-1">
                        {section.footer}
                    </div>
                </>
            )}
        </>
    )
}
