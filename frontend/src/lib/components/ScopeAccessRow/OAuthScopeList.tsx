import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { OAuthScopeGroup, OAuthScopeRow } from 'lib/oauthScopeRows'
import type { ScopeAccessLevel } from 'lib/scopes'

import { ScopeAccessGroup } from './ScopeAccessGroup'
import { ScopeAccessRow } from './ScopeAccessRow'

interface OAuthScopeListProps {
    appName: string
    identityScopeDescriptions: string[]
    /** Rows with nothing to choose, shown as a checkmark list. */
    requiredScopeRows: OAuthScopeRow[]
    adjustableScopeRows: OAuthScopeRow[]
    /** The adjustable rows in groups, or null to list them flat. */
    scopeGroups: OAuthScopeGroup[] | null
    /** Hides the "Required" tag when every row is required, because it then tells the person nothing. */
    allScopesRequired: boolean
    onChangeRow: (scopeObject: string, level: ScopeAccessLevel) => void
    onChangeGroup: (scopeObjects: string[], level: ScopeAccessLevel) => void
    dataAttrPrefix: string
}

/** The permissions an OAuth client asks for: fixed ones as checkmarks, the rest with an access control. */
export function OAuthScopeList({
    appName,
    identityScopeDescriptions,
    requiredScopeRows,
    adjustableScopeRows,
    scopeGroups,
    allScopesRequired,
    onChangeRow,
    onChangeGroup,
    dataAttrPrefix,
}: OAuthScopeListProps): JSX.Element {
    return (
        <>
            {(identityScopeDescriptions.length > 0 || requiredScopeRows.length > 0) && (
                <ul className="space-y-2">
                    {identityScopeDescriptions.map((description) => (
                        <li key={description} className="flex items-center space-x-2">
                            <IconCheck color="var(--success)" className="shrink-0" />
                            <span className="font-medium">{description}</span>
                        </li>
                    ))}
                    {requiredScopeRows.map((row) => (
                        <li key={row.key} className="space-y-1">
                            <div className="flex items-center space-x-2">
                                <IconCheck color="var(--success)" className="shrink-0" />
                                <span className="font-medium">{row.description}</span>
                                {row.alreadyGranted ? (
                                    <Tooltip title={`You granted this to ${appName} before`}>
                                        <LemonTag>Already granted</LemonTag>
                                    </Tooltip>
                                ) : (
                                    !allScopesRequired && (
                                        <Tooltip title={`${appName} requires this permission`}>
                                            <LemonTag>Required</LemonTag>
                                        </Tooltip>
                                    )
                                )}
                            </div>
                            {row.warning ? (
                                <div className="flex items-start gap-2 text-xs italic pl-6">
                                    <IconWarning className="text-base text-secondary mt-0.5" />
                                    <span>{row.warning}</span>
                                </div>
                            ) : null}
                        </li>
                    ))}
                </ul>
            )}
            {scopeGroups ? (
                <div className="flex flex-col">
                    {scopeGroups.map((group) => (
                        <ScopeAccessGroup
                            key={group.label}
                            group={group}
                            onChangeRow={onChangeRow}
                            onChangeGroup={onChangeGroup}
                            dataAttrPrefix={dataAttrPrefix}
                        />
                    ))}
                </div>
            ) : (
                adjustableScopeRows.length > 0 && (
                    <div className="flex flex-col">
                        {adjustableScopeRows.map((row) => (
                            <ScopeAccessRow key={row.key} row={row} onChange={onChangeRow} />
                        ))}
                    </div>
                )
            )}
        </>
    )
}
