import { type ScopeAccessLevel, type ScopeAccessRowModel } from 'lib/scopes'

import { ScopeAccessRow } from './ScopeAccessRow'

interface ScopeAccessRowControlProps {
    row: ScopeAccessRowModel
    onChange: (scopeObject: string, level: ScopeAccessLevel) => void
}

/** A row of a scope picker built from the shared row model. */
export function ScopeAccessRowControl({ row, onChange }: ScopeAccessRowControlProps): JSX.Element {
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
