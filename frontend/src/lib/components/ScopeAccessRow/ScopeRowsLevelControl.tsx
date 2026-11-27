import { LemonSegmentedButton } from '@posthog/lemon-ui'

import {
    type ScopeAccessLevel,
    type ScopePickerRow,
    scopeGroupDisabledReasons,
    scopeGroupLevel,
    scopeGroupTooltip,
} from 'lib/scopes'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { QuillScopeRowsLevelControl } from './QuillScopeRowsLevelControl'

interface ScopeRowsLevelControlProps {
    rows: ScopePickerRow[]
    onChange: (scopeObjects: string[], level: ScopeAccessLevel) => void
    ariaLabel: string
    dataAttrPrefix: string
}

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
    const quillSurface = useQuillSurface()

    if (quillSurface) {
        return (
            <QuillScopeRowsLevelControl
                value={value}
                disabledReasons={disabledReasons}
                valueTooltip={valueTooltip}
                onChange={(level) => onChange(keys, level)}
                ariaLabel={ariaLabel}
                dataAttrPrefix={dataAttrPrefix}
            />
        )
    }

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
