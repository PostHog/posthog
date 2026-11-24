import clsx from 'clsx'

import {
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import { capitalizeFirstLetter } from 'lib/utils/strings'

import { InsightColor } from '~/types'

const SWATCH_CLASSES: Record<InsightColor, string> = {
    [InsightColor.White]: '',
    [InsightColor.Black]: 'bg-[var(--black)]',
    [InsightColor.Blue]: 'bg-[var(--blue)]',
    [InsightColor.Green]: 'bg-[var(--green)]',
    [InsightColor.Purple]: 'bg-[var(--purple)]',
}

export function QuillInsightCardColorSubMenu({
    current,
    update,
}: {
    current: InsightColor
    update: (color: InsightColor) => void
}): JSX.Element {
    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger>Set color</DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                <DropdownMenuRadioGroup value={current} onValueChange={(color: InsightColor) => update(color)}>
                    {Object.values(InsightColor).map((color) => (
                        <DropdownMenuRadioItem key={color} value={color}>
                            {color !== InsightColor.White && (
                                <span className={clsx('size-3 rounded-full', SWATCH_CLASSES[color])} />
                            )}
                            {color !== InsightColor.White ? capitalizeFirstLetter(color) : 'No color'}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
