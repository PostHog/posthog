import { ScopeAccessGroup } from 'lib/components/ScopeAccessRow/ScopeAccessGroup'
import { countScopeRowsByLevel, type ScopeAccessLevel } from 'lib/scopes'

import { type OAuthScopeRow, scopeGroupAccessLevel, scopeGroupLevelTooltip } from './oauthAuthorizeLogic'
import { OAuthScopeRowControl } from './OAuthScopeRowControl'

interface OAuthScopeGroupControlProps {
    label: string
    rows: OAuthScopeRow[]
    appName: string
    onChangeRow: (scopeObject: string, level: ScopeAccessLevel) => void
    onChangeGroup: (scopeObjects: string[], level: ScopeAccessLevel) => void
}

export function OAuthScopeGroupControl({
    label,
    rows,
    appName,
    onChangeRow,
    onChangeGroup,
}: OAuthScopeGroupControlProps): JSX.Element {
    const groupLevel = scopeGroupAccessLevel(rows)
    const keys = rows.map((row) => row.key)
    const anyWritable = rows.some((row) => row.maxLevel === 'write')
    const allRequired = rows.every((row) => row.minLevel !== 'none')

    return (
        <ScopeAccessGroup
            label={label}
            counts={countScopeRowsByLevel(rows)}
            value={groupLevel}
            valueTooltip={scopeGroupLevelTooltip(rows, groupLevel, appName)}
            onChange={(level) => onChangeGroup(keys, level)}
            noneDisabledReason={allRequired ? `${appName} requires these permissions` : undefined}
            writeDisabledReason={anyWritable ? undefined : `Not requested by ${appName}`}
            dataAttrPrefix="oauth-scope-group"
        >
            {rows.map((row) => (
                <OAuthScopeRowControl key={row.key} row={row} appName={appName} onChange={onChangeRow} />
            ))}
        </ScopeAccessGroup>
    )
}
