import clsx from 'clsx'
import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import type { OAuthScopeRow, ScopeAccessLevel } from './oauthAuthorizeLogic'
import { OAuthScopeRowControl } from './OAuthScopeRowControl'

interface OAuthScopeGroupProps {
    label: string
    rows: OAuthScopeRow[]
    appName: string
    defaultOpen?: boolean
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

export function OAuthScopeGroup({
    label,
    rows,
    appName,
    defaultOpen = false,
    onChangeRow,
    onChangeGroup,
}: OAuthScopeGroupProps): JSX.Element {
    const [open, setOpen] = useState(defaultOpen)
    const counts = countByLevel(rows)
    const uniformLevel = rows.every((row) => row.value === rows[0].value) ? rows[0].value : undefined
    const keys = rows.map((row) => row.key)
    const anyWritable = rows.some((row) => row.maxLevel === 'write')
    const allRequired = rows.every((row) => row.minLevel !== 'none')
    const groupSlug = label.toLowerCase().replace(/[^a-z0-9]+/g, '-')

    const renderRow = (row: OAuthScopeRow): JSX.Element => (
        <OAuthScopeRowControl key={row.key} row={row} appName={appName} onChange={onChangeRow} />
    )

    // A resource that maps to a single scope of the same name has nothing to fold: the row
    // alone says everything the header would.
    if (rows.length === 1 && rows[0].label === label) {
        return <div className="border-t border-border first:border-t-0 py-1">{renderRow(rows[0])}</div>
    }

    return (
        <div className="border-t border-border first:border-t-0">
            <div className="flex items-center gap-2 py-2 min-h-10">
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={
                        <IconChevronRight
                            className={clsx('transition-transform motion-reduce:transition-none', open && 'rotate-90')}
                        />
                    }
                    onClick={() => setOpen(!open)}
                    aria-expanded={open}
                    aria-label={open ? `Collapse ${label}` : `Expand ${label}`}
                    data-attr={`oauth-scope-group-toggle-${groupSlug}`}
                />
                <button
                    type="button"
                    className="flex-1 min-w-0 text-left font-semibold truncate cursor-pointer bg-transparent border-0 p-0 text-inherit"
                    onClick={() => setOpen(!open)}
                >
                    {label}
                </button>
                <span className="text-xs text-muted whitespace-nowrap">
                    {rows.length} {rows.length === 1 ? 'permission' : 'permissions'}
                </span>
                <span className="flex items-center gap-1">
                    {counts.write > 0 && (
                        <LemonTag size="small" type="warning">
                            {counts.write} write
                        </LemonTag>
                    )}
                    {counts.read > 0 && (
                        <LemonTag size="small" type="success">
                            {counts.read} read
                        </LemonTag>
                    )}
                    {counts.none > 0 && (
                        <LemonTag size="small" type="muted">
                            {counts.none} none
                        </LemonTag>
                    )}
                </span>
                <LemonSegmentedButton
                    size="xsmall"
                    value={uniformLevel}
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
                    ]}
                />
            </div>
            {open && <div className="flex flex-col pb-2 pl-7">{rows.map(renderRow)}</div>}
        </div>
    )
}
