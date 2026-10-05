import { ScopeAccessGroup } from 'lib/components/ScopeAccessRow/ScopeAccessGroup'
import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'
import { countScopeRowsByLevel, type ScopeAccessLevel } from 'lib/scopes'

import {
    type PersonalAPIKeyScopeGroup as PersonalAPIKeyScopeGroupType,
    scopeGroupAccessLevel,
    scopeGroupLevelTooltip,
} from './personalAPIKeysLogic'

interface PersonalAPIKeyScopeGroupProps {
    group: PersonalAPIKeyScopeGroupType
    defaultOpen: boolean
    onChangeRow: (scopeObject: string, level: ScopeAccessLevel) => void
    onChangeGroup: (scopeObjects: string[], level: ScopeAccessLevel) => void
}

export function PersonalAPIKeyScopeGroup({
    group,
    defaultOpen,
    onChangeRow,
    onChangeGroup,
}: PersonalAPIKeyScopeGroupProps): JSX.Element {
    const { label, rows } = group
    const groupLevel = scopeGroupAccessLevel(rows)
    const keys = rows.map((row) => row.scope.key)
    // A level that no row can take is disabled on the group, with the reason the rows give.
    const groupDisabledReason = (reason: 'readDisabledReason' | 'writeDisabledReason'): string | undefined =>
        rows.every((row) => row[reason]) ? rows[0]?.[reason] : undefined

    return (
        <ScopeAccessGroup
            label={label}
            counts={countScopeRowsByLevel(rows)}
            value={groupLevel}
            valueTooltip={scopeGroupLevelTooltip(rows, groupLevel)}
            onChange={(level) => onChangeGroup(keys, level)}
            readDisabledReason={groupDisabledReason('readDisabledReason')}
            writeDisabledReason={groupDisabledReason('writeDisabledReason')}
            defaultOpen={defaultOpen}
            dataAttrPrefix="personal-api-key-scope-group"
        >
            {rows.map(({ scope, value, muted, readDisabledReason, writeDisabledReason }) => (
                <ScopeAccessRow
                    key={scope.key}
                    label={scope.objectName}
                    info={scope.info}
                    muted={muted}
                    value={value}
                    onChange={(level) => onChangeRow(scope.key, level as ScopeAccessLevel)}
                    readDisabledReason={readDisabledReason}
                    writeDisabledReason={writeDisabledReason}
                    warning={value === 'none' ? undefined : scope.warnings?.[value]}
                />
            ))}
        </ScopeAccessGroup>
    )
}
