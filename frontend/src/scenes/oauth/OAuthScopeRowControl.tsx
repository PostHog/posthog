import { ScopeAccessRow } from 'lib/components/ScopeAccessRow/ScopeAccessRow'

import type { OAuthScopeRow, ScopeAccessLevel } from './oauthAuthorizeLogic'

interface OAuthScopeRowControlProps {
    row: OAuthScopeRow
    appName: string
    onChange: (scopeObject: string, level: ScopeAccessLevel) => void
}

export function OAuthScopeRowControl({ row, appName, onChange }: OAuthScopeRowControlProps): JSX.Element {
    return (
        <ScopeAccessRow
            label={row.label}
            info={row.info}
            muted={row.value === 'none'}
            value={row.value}
            onChange={(value) => onChange(row.key, value as ScopeAccessLevel)}
            noneDisabledReason={
                row.minLevel !== 'none' ? `${appName} requires at least ${row.minLevel} access` : undefined
            }
            writeDisabledReason={row.maxLevel !== 'write' ? `Not requested by ${appName}` : undefined}
            warning={row.warning}
        />
    )
}
