import {
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { AccessControlLevel } from '~/types'

import type { InheritedAccess } from '../accessControlLogic'
import { humanizeAccessControlLevel } from '../ResourceAccessControlsV2/helpers'

export interface QuillAccessLevelSelectProps {
    /** The subject's own saved rule; null means no rule ("No override"). */
    level: AccessControlLevel | null
    levels: AccessControlLevel[]
    onChange: (newValue: AccessControlLevel | null) => void
    disabledReason?: string
    /** Levels below this are offered but disabled. */
    minimumLevel?: AccessControlLevel | null
    /**
     * What applies when there is no rule. Passing it offers "No override" as a way back,
     * rendered as `No override · <level>` with the reason in the tooltip and menu entry.
     */
    inherited?: InheritedAccess | null
}

type LevelItem = { value: AccessControlLevel | null; label: string }

export function QuillAccessLevelSelect({
    level,
    levels,
    onChange,
    disabledReason,
    minimumLevel,
    inherited,
}: QuillAccessLevelSelectProps): JSX.Element {
    const minimumIndex = minimumLevel ? levels.indexOf(minimumLevel) : -1
    const items: LevelItem[] = [
        ...(inherited ? [{ value: null, label: 'No override' }] : []),
        ...levels.map((value) => ({ value, label: humanizeAccessControlLevel(value) })),
    ]

    // The trigger and the menu entry read identically, so what you pick is what you end up looking at.
    // The inherited half drops to a muted color so it reads as a consequence, not a second value.
    const noOverrideLabel = inherited ? (
        <span className="whitespace-nowrap">
            No override <span className="text-muted-foreground">· {inherited.label}</span>
        </span>
    ) : (
        'No override'
    )

    // A disabled control explains itself through disabledReason; adding the inherited
    // reason on top reads as two unrelated sentences
    const tooltip =
        disabledReason ??
        (!inherited
            ? undefined
            : level === null
              ? inherited.reason
              : `Overrides ${inherited.label}. ${inherited.reason}.`)

    const value = (
        <SelectValue>
            {(selected: AccessControlLevel | null) =>
                selected === null ? (
                    inherited ? (
                        noOverrideLabel
                    ) : (
                        <span className="text-muted-foreground">Select level…</span>
                    )
                ) : (
                    humanizeAccessControlLevel(selected)
                )
            }
        </SelectValue>
    )

    return (
        <Select<AccessControlLevel | null>
            items={items}
            value={level}
            onValueChange={(next) => onChange(next as AccessControlLevel | null)}
            disabled={!!disabledReason}
        >
            {tooltip ? (
                <Tooltip>
                    <TooltipTrigger delay={0} render={<SelectTrigger className="shrink-0" />}>
                        {value}
                    </TooltipTrigger>
                    <TooltipContent>{tooltip}</TooltipContent>
                </Tooltip>
            ) : (
                <SelectTrigger className="shrink-0">{value}</SelectTrigger>
            )}
            <SelectContent>
                {inherited && (
                    <>
                        <SelectGroup>
                            <SelectItem value={null}>
                                <span className="flex flex-col items-start gap-1 py-1">
                                    {noOverrideLabel}
                                    <Text size="xs" variant="muted" render={<span className="whitespace-nowrap" />}>
                                        {inherited.reason}
                                    </Text>
                                </span>
                            </SelectItem>
                        </SelectGroup>
                        <SelectSeparator />
                    </>
                )}
                <SelectGroup>
                    {levels.map((option, index) => {
                        const unavailable = index < minimumIndex
                        return (
                            <SelectItem key={option} value={option} disabled={unavailable}>
                                <span className="flex flex-col items-start gap-0.5">
                                    {humanizeAccessControlLevel(option)}
                                    {unavailable && (
                                        <Text size="xs" variant="muted" render={<span />}>
                                            Not available for this resource type
                                        </Text>
                                    )}
                                </span>
                            </SelectItem>
                        )
                    })}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}
