import { Fragment } from 'react'

import { LemonSelectSection } from '@posthog/lemon-ui'
import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

export function QuillThemeSwitcher({
    sections,
    value,
    onChange,
}: {
    sections: LemonSelectSection<string>[]
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const leaves = sections.flatMap((section) => section.options.filter((option) => 'value' in option))

    return (
        <Select value={value} onValueChange={(next) => next && onChange(next)}>
            <SelectTrigger aria-label="Color theme" className="w-fit min-w-48">
                <SelectValue>
                    {(selected: string) => leaves.find((leaf) => leaf.value === selected)?.label ?? 'Sync with system'}
                </SelectValue>
            </SelectTrigger>
            <SelectContent>
                {sections.map((section, index) => (
                    <Fragment key={index}>
                        {index > 0 && <SelectSeparator />}
                        <SelectGroup>
                            {section.options.map((option) =>
                                'value' in option ? (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.icon}
                                        {option.label}
                                    </SelectItem>
                                ) : null
                            )}
                        </SelectGroup>
                    </Fragment>
                ))}
            </SelectContent>
        </Select>
    )
}
