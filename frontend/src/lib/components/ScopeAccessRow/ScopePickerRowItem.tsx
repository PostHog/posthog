import { type ScopeAccessLevel, type ScopePickerRow } from 'lib/scopes'

import { ScopeAccessRow } from './ScopeAccessRow'

interface ScopePickerRowItemProps {
    row: ScopePickerRow
    onChange: (scopeObject: string, level: ScopeAccessLevel) => void
}

/** Renders a `ScopePickerRow` through `ScopeAccessRow`, the row control with flat props. */
export function ScopePickerRowItem({ row, onChange }: ScopePickerRowItemProps): JSX.Element {
    return (
        <ScopeAccessRow
            label={row.label}
            info={row.info}
            muted={row.muted}
            value={row.value}
            onChange={(level) => onChange(row.key, level as ScopeAccessLevel)}
            noneDisabledReason={row.disabledReasons.none}
            readDisabledReason={row.disabledReasons.read}
            writeDisabledReason={row.disabledReasons.write}
            warning={row.warning}
        />
    )
}
