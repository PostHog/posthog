import clsx from 'clsx'
import { useId, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import {
    type ScopePickerGroup,
    type ScopeAccessLevel,
    countScopeRowsByLevel,
    scopeGroupLevel,
    scopeGroupDisabledReasons,
    scopeGroupTooltip,
} from 'lib/scopes'

import { ScopePickerRowItem } from './ScopePickerRowItem'

interface ScopeAccessGroupProps {
    group: ScopePickerGroup
    onChangeRow: (scopeObject: string, level: ScopeAccessLevel) => void
    onChangeGroup: (scopeObjects: string[], level: ScopeAccessLevel) => void
    /** Whether the rows show on first render. */
    defaultOpen?: boolean
    /** Prefix of the `data-attr`s: `<prefix>-toggle-<slug>` on the toggle, `<prefix>-<slug>-<level>` on an option. */
    dataAttrPrefix: string
}

/** A collapsible group of scope rows with a control that sets every row at once. */
export function ScopeAccessGroup({
    group,
    onChangeRow,
    onChangeGroup,
    defaultOpen = false,
    dataAttrPrefix,
}: ScopeAccessGroupProps): JSX.Element {
    const { label, rows } = group
    const [open, setOpen] = useState(defaultOpen)
    const panelId = useId()
    const counts = countScopeRowsByLevel(rows)
    const value = scopeGroupLevel(rows)
    const disabledReasons = scopeGroupDisabledReasons(rows)
    const valueTooltip = scopeGroupTooltip(rows, value)
    const keys = rows.map((row) => row.key)
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
                    data-attr={`${dataAttrPrefix}-toggle-${groupSlug}`}
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
                            value={value}
                            onChange={(level) => onChangeGroup(keys, level as ScopeAccessLevel)}
                            options={[
                                { label: 'No access', value: 'none' as const },
                                { label: 'Read', value: 'read' as const },
                                { label: 'Write', value: 'write' as const },
                            ].map((option) => ({
                                ...option,
                                disabledReason: disabledReasons[option.value],
                                // Tells a group change apart from a row change in autocapture.
                                'data-attr': `${dataAttrPrefix}-${groupSlug}-${option.value}`,
                                tooltip: option.value === value ? valueTooltip : undefined,
                            }))}
                        />
                    </div>
                </div>
            </div>
            {open && (
                <div id={panelId} className="flex flex-col pb-2 pl-7">
                    {rows.map((row) => (
                        <ScopePickerRowItem key={row.key} row={row} onChange={onChangeRow} />
                    ))}
                </div>
            )}
        </div>
    )
}
