import { LemonSegmentedButton } from '@posthog/lemon-ui'

import {
    type ScopeAccessLevel,
    type ScopePickerRow,
    scopeGroupDisabledReasons,
    scopeGroupLevel,
    scopeGroupTooltip,
} from 'lib/scopes'

interface ScopeRowsLevelControlProps {
    rows: ScopePickerRow[]
    onChange: (scopeObjects: string[], level: ScopeAccessLevel) => void
    /** Names the control for screen readers, e.g. "Product analytics access". */
    ariaLabel: string
    /** Prefix of each option's `data-attr`: `<prefix>-<level>`. */
    dataAttrPrefix: string
}

/** A No access / Read / Write control that sets several scope rows at once. */
export function ScopeRowsLevelControl({
    rows,
    onChange,
    ariaLabel,
    dataAttrPrefix,
}: ScopeRowsLevelControlProps): JSX.Element {
    const value = scopeGroupLevel(rows)
    const disabledReasons = scopeGroupDisabledReasons(rows)
    const valueTooltip = scopeGroupTooltip(rows, value)
    const keys = rows.map((row) => row.key)

    return (
        <div role="group" aria-label={ariaLabel}>
            <LemonSegmentedButton
                size="xsmall"
                value={value}
                onChange={(level) => onChange(keys, level as ScopeAccessLevel)}
                options={[
                    { label: 'No access', value: 'none' as const },
                    { label: 'Read', value: 'read' as const },
                    { label: 'Write', value: 'write' as const },
                ].map((option) => ({
                    ...option,
                    disabledReason: disabledReasons[option.value],
                    // Tells a group or list-wide change apart from a row change in autocapture.
                    'data-attr': `${dataAttrPrefix}-${option.value}`,
                    tooltip: option.value === value ? valueTooltip : undefined,
                }))}
            />
        </div>
    )
}
