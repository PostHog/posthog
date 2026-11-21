import { ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { ScopeAccessLevel } from 'lib/scopes'

import { SCOPE_LEVEL_OPTIONS } from './QuillScopeAccessRow'

export function QuillScopeRowsLevelControl({
    value,
    disabledReasons,
    valueTooltip,
    onChange,
    ariaLabel,
    dataAttrPrefix,
}: {
    value: ScopeAccessLevel | undefined
    disabledReasons: Partial<Record<ScopeAccessLevel, string>>
    valueTooltip: string | undefined
    onChange: (level: ScopeAccessLevel) => void
    ariaLabel: string
    dataAttrPrefix: string
}): JSX.Element {
    return (
        <ToggleGroup
            variant="outline"
            size="sm"
            aria-label={ariaLabel}
            value={value ? [value] : []}
            onValueChange={(next: string[]) => next[0] && onChange(next[0] as ScopeAccessLevel)}
        >
            {SCOPE_LEVEL_OPTIONS.map((option) => {
                // Tells a group or list-wide change apart from a row change in autocapture.
                const dataAttr = `${dataAttrPrefix}-${option.value}`
                const disabledReason = disabledReasons[option.value]

                if (option.value === value && valueTooltip && !disabledReason) {
                    return (
                        <Tooltip key={option.value}>
                            <TooltipTrigger render={<ToggleGroupItem value={option.value} data-attr={dataAttr} />}>
                                {option.label}
                            </TooltipTrigger>
                            <TooltipContent className="max-w-80">{valueTooltip}</TooltipContent>
                        </Tooltip>
                    )
                }

                return (
                    <ToggleGroupItem
                        key={option.value}
                        value={option.value}
                        disabledReason={disabledReason}
                        data-attr={dataAttr}
                    >
                        {option.label}
                    </ToggleGroupItem>
                )
            })}
        </ToggleGroup>
    )
}
