import clsx from 'clsx'
import { useId, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import {
    type OAuthScopeRow,
    type ScopeAccessLevel,
    scopeGroupAccessLevel,
    scopeGroupLevelTooltip,
} from './oauthAuthorizeLogic'
import { OAuthScopeRowControl } from './OAuthScopeRowControl'

interface OAuthScopeGroupControlProps {
    label: string
    rows: OAuthScopeRow[]
    appName: string
    onChangeRow: (scopeObject: string, level: ScopeAccessLevel) => void
    onChangeGroup: (scopeObjects: string[], level: ScopeAccessLevel) => void
}

const countByLevel = (rows: OAuthScopeRow[]): Record<ScopeAccessLevel, number> => {
    const counts: Record<ScopeAccessLevel, number> = { none: 0, read: 0, write: 0 }
    for (const row of rows) {
        counts[row.value] += 1
    }
    return counts
}

export function OAuthScopeGroupControl({
    label,
    rows,
    appName,
    onChangeRow,
    onChangeGroup,
}: OAuthScopeGroupControlProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const panelId = useId()
    const counts = countByLevel(rows)
    const groupLevel = scopeGroupAccessLevel(rows)
    const groupLevelTooltip = scopeGroupLevelTooltip(rows, groupLevel, appName)
    const keys = rows.map((row) => row.key)
    const anyWritable = rows.some((row) => row.maxLevel === 'write')
    const allRequired = rows.every((row) => row.minLevel !== 'none')
    const groupSlug = label.toLowerCase().replace(/[^a-z0-9]+/g, '-')

    return (
        <div className="border-t border-border first:border-t-0 @container/scope-group">
            {/* The header stays on one line. In a narrow container, such as an OAuth popup window,
                the label truncates and the counts hide, so the control keeps its place. */}
            <div className="flex items-center gap-2 py-2 min-h-10">
                <button
                    type="button"
                    className="flex items-center gap-2 flex-1 min-w-0 text-left font-semibold cursor-pointer bg-transparent border-0 p-0 text-inherit"
                    onClick={() => setOpen(!open)}
                    aria-expanded={open}
                    aria-controls={panelId}
                    data-attr={`oauth-scope-group-toggle-${groupSlug}`}
                >
                    <IconChevronRight
                        className={clsx(
                            'shrink-0 text-muted transition-transform motion-reduce:transition-none',
                            open && 'rotate-90'
                        )}
                    />
                    <span className="truncate">{label}</span>
                </button>
                <div className="flex items-center gap-2 ml-auto shrink-0">
                    <span className="hidden @min-[36rem]/scope-group:flex items-center gap-2">
                        <span className="text-xs text-muted whitespace-nowrap">
                            <span translate="no">{rows.length}</span> {rows.length === 1 ? 'permission' : 'permissions'}
                        </span>
                        <span className="flex items-center gap-1">
                            {/* Same order as the segmented control: no access, read, write. */}
                            {counts.none > 0 && (
                                <LemonTag size="small" type="muted">
                                    <span translate="no">{counts.none}</span> none
                                </LemonTag>
                            )}
                            {counts.read > 0 && (
                                <LemonTag size="small" type="success">
                                    <span translate="no">{counts.read}</span> read
                                </LemonTag>
                            )}
                            {counts.write > 0 && (
                                <LemonTag size="small" type="warning">
                                    <span translate="no">{counts.write}</span> write
                                </LemonTag>
                            )}
                        </span>
                    </span>
                    <div role="group" aria-label={`${label} access`}>
                        <LemonSegmentedButton
                            size="xsmall"
                            value={groupLevel}
                            onChange={(level) => onChangeGroup(keys, level as ScopeAccessLevel)}
                            options={[
                                {
                                    label: 'No access',
                                    value: 'none',
                                    disabledReason: allRequired ? `${appName} requires these permissions` : undefined,
                                },
                                { label: 'Read', value: 'read' },
                                {
                                    label: 'Write',
                                    value: 'write',
                                    disabledReason: anyWritable ? undefined : `Not requested by ${appName}`,
                                },
                            ].map((option) =>
                                option.value === groupLevel ? { ...option, tooltip: groupLevelTooltip } : option
                            )}
                        />
                    </div>
                </div>
            </div>
            {open && (
                <div id={panelId} className="flex flex-col pb-2 pl-7">
                    {rows.map((row) => (
                        <OAuthScopeRowControl key={row.key} row={row} appName={appName} onChange={onChangeRow} />
                    ))}
                </div>
            )}
        </div>
    )
}
