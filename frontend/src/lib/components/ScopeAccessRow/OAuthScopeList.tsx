import clsx from 'clsx'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { type OAuthScopeGroup, scopeGroupsStartOpen } from 'lib/oauthScopeRows'
import type { ScopeAccessLevel } from 'lib/scopes'

import { ScopeAccessGroup } from './ScopeAccessGroup'
import { ScopeRowsLevelControl } from './ScopeRowsLevelControl'

interface OAuthScopeListProps {
    groups: OAuthScopeGroup[]
    onChangeRow: (scopeObject: string, level: ScopeAccessLevel) => void
    onChangeGroup: (scopeObjects: string[], level: ScopeAccessLevel) => void
    dataAttrPrefix: string
    headerClassName?: string
    bodyClassName?: string
}

export function OAuthScopeList({
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
            <div className={clsx('flex flex-col', bodyClassName)}>
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
        </>
    )
}
