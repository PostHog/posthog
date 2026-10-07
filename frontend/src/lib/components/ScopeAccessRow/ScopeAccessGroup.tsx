import clsx from 'clsx'
import { type ReactNode, useId, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import type { ScopeAccessLevel } from 'lib/scopes'

interface ScopeAccessGroupProps {
    /** Group heading, such as a product area. */
    label: string
    /** How many rows in the group sit at each level, for the tags in the header. */
    counts: Record<ScopeAccessLevel, number>
    /** The level the group control shows as selected. Undefined when the rows disagree. */
    value: ScopeAccessLevel | undefined
    /** Called with the level the user picks for the whole group. */
    onChange: (level: ScopeAccessLevel) => void
    /** Reason the No access option should be disabled. Set to a non-empty string to disable. */
    noneDisabledReason?: string
    /** Reason the Read option should be disabled. Set to a non-empty string to disable. */
    readDisabledReason?: string
    /** Reason the Write option should be disabled. Set to a non-empty string to disable. */
    writeDisabledReason?: string
    /** Tooltip on the selected level, for when some rows sit at another level. */
    valueTooltip?: string
    /** Whether the rows show on first render. */
    defaultOpen?: boolean
    /** Prefix of the `data-attr`s: `<prefix>-toggle-<slug>` on the toggle, `<prefix>-<slug>-<level>` on an option. */
    dataAttrPrefix: string
    /** The rows of the group, rendered when the group is open. */
    children: ReactNode
}

export function ScopeAccessGroup({
    label,
    counts,
    value,
    onChange,
    noneDisabledReason,
    readDisabledReason,
    writeDisabledReason,
    valueTooltip,
    defaultOpen = false,
    dataAttrPrefix,
    children,
}: ScopeAccessGroupProps): JSX.Element {
    const [open, setOpen] = useState(defaultOpen)
    const panelId = useId()
    const total = counts.none + counts.read + counts.write
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
                            <span translate="no">{total}</span> {total === 1 ? 'permission' : 'permissions'}
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
                            onChange={(level) => onChange(level as ScopeAccessLevel)}
                            options={[
                                { label: 'No access', value: 'none', disabledReason: noneDisabledReason },
                                { label: 'Read', value: 'read', disabledReason: readDisabledReason },
                                { label: 'Write', value: 'write', disabledReason: writeDisabledReason },
                            ].map((option) => ({
                                ...option,
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
                    {children}
                </div>
            )}
        </div>
    )
}
