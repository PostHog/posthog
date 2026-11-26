import { IconLock, IconWarning } from '@posthog/icons'
import {
    Badge,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import type { ScopeAccessLevel, ScopePickerGroup, ScopePickerRow } from 'lib/scopes'

import { ScopeAccessRow } from './ScopeAccessRow'
import { ScopeRowsLevelControl } from './ScopeRowsLevelControl'

function HiddenRowMarker({ title, children }: { title: string; children: JSX.Element }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex shrink-0" />}>{children}</TooltipTrigger>
            <TooltipContent>{title}</TooltipContent>
        </Tooltip>
    )
}

function HiddenRowMarkers({ rows }: { rows: ScopePickerRow[] }): JSX.Element {
    return (
        <>
            {rows.some((row) => row.disabledReasons.none) && (
                <HiddenRowMarker title="Some of these permissions can't be removed">
                    <IconLock className="text-muted-foreground" />
                </HiddenRowMarker>
            )}
            {rows.some((row) => row.warning) && (
                <HiddenRowMarker title="Some of these permissions have a warning">
                    <IconWarning className="text-warning-foreground" />
                </HiddenRowMarker>
            )}
        </>
    )
}

export function QuillScopeAccessGroup({
    group,
    open,
    onOpenChange,
    counts,
    groupSlug,
    onChangeRow,
    onChangeGroup,
    dataAttrPrefix,
}: {
    group: ScopePickerGroup
    open: boolean
    onOpenChange: (open: boolean) => void
    counts: Record<ScopeAccessLevel, number>
    groupSlug: string
    onChangeRow: (scopeObject: string, level: ScopeAccessLevel) => void
    onChangeGroup: (scopeObjects: string[], level: ScopeAccessLevel) => void
    dataAttrPrefix: string
}): JSX.Element {
    const { label, rows } = group

    return (
        <Collapsible
            variant="folder"
            open={open}
            onOpenChange={onOpenChange}
            className="@container/scope-group border-t border-border first:border-t-0"
        >
            {/* The header stays on one line. In a narrow container the label truncates and the counts
                hide, so the control keeps its place. */}
            <CollapsibleHeader className="min-h-10 gap-2 py-2">
                <CollapsibleTrigger
                    className="min-w-0 flex-1 font-semibold"
                    data-attr={`${dataAttrPrefix}-toggle-${groupSlug}`}
                >
                    <span className="truncate">{label}</span>
                </CollapsibleTrigger>
                {/* A closed group hides its rows, so it shows that some of them are locked or carry a warning. */}
                {!open && <HiddenRowMarkers rows={rows} />}
                <div className="ms-auto flex shrink-0 items-center gap-2">
                    <span className="hidden items-center gap-2 @min-[36rem]/scope-group:flex">
                        <Text size="xs" variant="muted" render={<span className="whitespace-nowrap" />}>
                            <span translate="no">{rows.length}</span> {rows.length === 1 ? 'permission' : 'permissions'}
                        </Text>
                        <span className="flex items-center gap-1">
                            {counts.none > 0 && (
                                <Badge>
                                    <span translate="no">{counts.none}</span> none
                                </Badge>
                            )}
                            {counts.read > 0 && (
                                <Badge variant="success">
                                    <span translate="no">{counts.read}</span> read
                                </Badge>
                            )}
                            {counts.write > 0 && (
                                <Badge variant="warning">
                                    <span translate="no">{counts.write}</span> write
                                </Badge>
                            )}
                        </span>
                    </span>
                    {!open && (
                        <ScopeRowsLevelControl
                            rows={rows}
                            onChange={onChangeGroup}
                            ariaLabel={`${label} access`}
                            dataAttrPrefix={`${dataAttrPrefix}-${groupSlug}`}
                        />
                    )}
                </div>
            </CollapsibleHeader>
            <CollapsibleContent className="flex flex-col pb-2 pl-7">
                {rows.map((row) => (
                    <ScopeAccessRow key={row.key} row={row} onChange={onChangeRow} />
                ))}
            </CollapsibleContent>
        </Collapsible>
    )
}
