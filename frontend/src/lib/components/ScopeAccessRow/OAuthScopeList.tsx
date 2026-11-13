import clsx from 'clsx'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { type OAuthScopeGroup, scopeGroupsStartOpen } from 'lib/oauthScopeRows'
import type { ScopeAccessLevel } from 'lib/scopes'

import { ScopeAccessGroup } from './ScopeAccessGroup'
import { ScopeRowsLevelControl } from './ScopeRowsLevelControl'

interface OAuthScopeListProps {
    /** The sentence for the identity scopes, or null when the client asked for none. */
    identitySummary: string | null
    groups: OAuthScopeGroup[]
    onChangeRow: (scopeObject: string, level: ScopeAccessLevel) => void
    onChangeGroup: (scopeObjects: string[], level: ScopeAccessLevel) => void
    /** Prefix of the `data-attr`s on the groups and on the control for every permission. */
    dataAttrPrefix: string
    /** Classes for the header row, such as the sticky styling of a scrolling card. */
    headerClassName?: string
    /** Classes for the identity sentence and the groups under the header. */
    bodyClassName?: string
}

/** The permissions an OAuth client asks for, in product-area groups that open or close together. */
export function OAuthScopeList({
    identitySummary,
    groups,
    onChangeRow,
    onChangeGroup,
    dataAttrPrefix,
    headerClassName,
    bodyClassName,
}: OAuthScopeListProps): JSX.Element {
    // Null until the person expands or collapses all, so the default follows the rows as they load.
    const [allOpenPick, setAllOpenPick] = useState<boolean | null>(null)
    const allOpen = allOpenPick ?? scopeGroupsStartOpen(groups)
    const allRows = groups.flatMap((group) => group.rows)
    const showListControls = groups.length > 1

    return (
        <>
            <div className={clsx('flex items-center justify-between gap-2 flex-wrap', headerClassName)}>
                <div className="text-sm font-semibold uppercase text-muted">Permissions</div>
                {showListControls && (
                    <div className="flex items-center gap-2 flex-wrap">
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => setAllOpenPick(!allOpen)}
                            data-attr={`${dataAttrPrefix}-${allOpen ? 'collapse' : 'expand'}-all`}
                        >
                            {allOpen ? 'Collapse all' : 'Expand all'}
                        </LemonButton>
                        <ScopeRowsLevelControl
                            rows={allRows}
                            onChange={onChangeGroup}
                            ariaLabel="Access for every permission"
                            dataAttrPrefix={`${dataAttrPrefix}-all`}
                        />
                    </div>
                )}
            </div>
            <div className={clsx('flex flex-col gap-2', bodyClassName)}>
                {identitySummary && <p className="m-0 text-secondary">{identitySummary}</p>}
                {groups.length > 0 && (
                    <div className="flex flex-col">
                        {groups.map((group) => (
                            <ScopeAccessGroup
                                // A group keeps its own open state, so a change of `allOpen` remounts it with the new default.
                                key={`${group.label}-${allOpen}`}
                                group={group}
                                defaultOpen={allOpen}
                                onChangeRow={onChangeRow}
                                onChangeGroup={onChangeGroup}
                                dataAttrPrefix={dataAttrPrefix}
                            />
                        ))}
                    </div>
                )}
            </div>
        </>
    )
}
