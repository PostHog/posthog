import { IconPlus } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { AccessControlLevel } from '~/types'

import type { QuillLevelSelectOption } from './QuillLevelSelect'

/** A button that adds a rule for a product with none yet, by picking its first level from a menu. */
export function QuillAddLevelMenu({
    label,
    options,
    onSelect,
    disabledReason,
}: {
    label: string
    options: QuillLevelSelectOption<AccessControlLevel>[]
    onSelect: (level: AccessControlLevel) => void
    disabledReason?: string
}): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button disabledReason={disabledReason} />}>
                <IconPlus />
                {label}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                {options.map((option) => (
                    <DropdownMenuItem
                        key={option.value}
                        disabledReason={option.disabledReason}
                        onClick={() => onSelect(option.value)}
                    >
                        {option.label}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
