import { IconInfo, IconLock, IconWarning } from '@posthog/icons'
import { Text, ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import type { ScopeAccessLevel, ScopePickerRow } from 'lib/scopes'

export const SCOPE_LEVEL_OPTIONS: { label: string; value: ScopeAccessLevel }[] = [
    { label: 'No access', value: 'none' },
    { label: 'Read', value: 'read' },
    { label: 'Write', value: 'write' },
]

function RowHint({ title, children }: { title: string | JSX.Element; children: JSX.Element }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex text-muted-foreground" />}>{children}</TooltipTrigger>
            <TooltipContent className="max-w-80">{title}</TooltipContent>
        </Tooltip>
    )
}

export function QuillScopeAccessRow({
    row,
    onChange,
}: {
    row: ScopePickerRow
    onChange: (scopeObject: string, level: ScopeAccessLevel) => void
}): JSX.Element {
    const { key, label, info, value, muted, warning, disabledReasons } = row

    return (
        <div className="flex flex-col gap-1">
            <div className="flex min-h-8 flex-wrap items-center justify-between gap-2">
                <div className={cn('flex items-center gap-1', muted && 'text-muted-foreground')}>
                    <Text size="xs" weight="semibold" render={<span />}>
                        {label}
                    </Text>
                    {disabledReasons.none ? (
                        <RowHint title={disabledReasons.none}>
                            <IconLock className="text-base" />
                        </RowHint>
                    ) : null}
                    {info ? (
                        <RowHint title={info}>
                            <IconInfo className="text-base" />
                        </RowHint>
                    ) : null}
                </div>
                <ToggleGroup
                    variant="outline"
                    size="sm"
                    aria-label={`${label} access`}
                    value={[value]}
                    onValueChange={(next: string[]) => next[0] && onChange(key, next[0] as ScopeAccessLevel)}
                >
                    {SCOPE_LEVEL_OPTIONS.map((option) => (
                        <ToggleGroupItem
                            key={option.value}
                            value={option.value}
                            disabledReason={disabledReasons[option.value]}
                        >
                            {option.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
            {warning ? (
                <div className="flex items-start gap-2 pb-2">
                    <IconWarning className="mt-0.5 shrink-0 text-base text-muted-foreground" />
                    <Text size="xs" variant="muted" render={<span />}>
                        {warning}
                    </Text>
                </div>
            ) : null}
        </div>
    )
}
