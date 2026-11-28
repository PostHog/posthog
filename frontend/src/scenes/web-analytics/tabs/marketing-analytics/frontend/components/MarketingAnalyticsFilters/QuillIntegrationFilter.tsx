import { IconFilter } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { SourceStatus } from '../../logic/marketingAnalyticsLogic'
import { QuillStatusIcon } from '../settings/QuillStatusIcon'

export interface IntegrationFilterSource {
    id: string
    name: string
    type: string
    prefix?: string
    status?: SourceStatus
    statusMessage?: string
}

export function QuillIntegrationFilter({
    open,
    onOpenChange,
    label,
    groups,
    selectedIds,
    isAllSelected,
    isSomeSelected,
    includeNonIntegrated,
    showNonIntegrated,
    formatSourceLabel,
    statusToShow,
    onToggleAll,
    onToggleSource,
    onToggleNonIntegrated,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    label: string
    groups: { title: string; sources: IntegrationFilterSource[] }[]
    selectedIds: string[]
    isAllSelected: boolean
    isSomeSelected: boolean
    includeNonIntegrated: boolean
    showNonIntegrated: boolean
    formatSourceLabel: (source: IntegrationFilterSource) => string
    statusToShow: (source: IntegrationFilterSource) => { status: SourceStatus; message: string } | null
    onToggleAll: () => void
    onToggleSource: (sourceId: string) => void
    onToggleNonIntegrated: () => void
}): JSX.Element {
    return (
        <DropdownMenu open={open} onOpenChange={(nextOpen) => onOpenChange(nextOpen)}>
            <DropdownMenuTrigger
                render={<Button variant="outline" data-attr="integration-filter" className="max-w-full" />}
            >
                <IconFilter />
                <span className="truncate">{label}</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="max-w-80">
                <DropdownMenuCheckboxItem
                    checked={isAllSelected}
                    closeOnClick={false}
                    onCheckedChange={() => onToggleAll()}
                >
                    {isAllSelected || isSomeSelected ? 'Clear all' : 'Select all'}
                </DropdownMenuCheckboxItem>
                <DropdownMenuSeparator />
                {groups.map((group) => (
                    <DropdownMenuGroup key={group.title}>
                        {group.title && <DropdownMenuLabel>{group.title}</DropdownMenuLabel>}
                        {group.sources.map((source) => {
                            const status = statusToShow(source)
                            return (
                                <DropdownMenuCheckboxItem
                                    key={source.id}
                                    checked={selectedIds.includes(source.id)}
                                    closeOnClick={false}
                                    onCheckedChange={() => onToggleSource(source.id)}
                                >
                                    <SourceIcon type={source.name} size="xsmall" disableTooltip />
                                    <span className="min-w-0 flex-1 truncate">{formatSourceLabel(source)}</span>
                                    {status && <QuillStatusIcon status={status.status} message={status.message} />}
                                </DropdownMenuCheckboxItem>
                            )
                        })}
                    </DropdownMenuGroup>
                ))}
                {showNonIntegrated && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuCheckboxItem
                            checked={includeNonIntegrated}
                            closeOnClick={false}
                            onCheckedChange={() => onToggleNonIntegrated()}
                            tooltip="Traffic no integration reports cost for, like organic, email, or a source you haven't mapped yet."
                        >
                            No integration
                        </DropdownMenuCheckboxItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
