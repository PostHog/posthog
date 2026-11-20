import { Fragment, useState } from 'react'

import {
    IconChevronDown,
    IconChevronRight,
    IconInfo,
    IconLogomark,
    IconPencil,
    IconPlus,
    IconTrash,
} from '@posthog/icons'
import {
    Badge,
    Button,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Input,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type {
    CustomPropertyDefinitionApi,
    CustomPropertyReferenceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import type { CustomPropertyTargetTypeFilter } from './customPropertyDefinitionsLogic'
import { CustomPropertyModal } from './CustomPropertyModal'
import { labelForDisplayType, type SourceSyncStatusLevel, sourceSyncStatus } from './customPropertyTypes'

const PAGE_SIZE = 20

const BADGE_VARIANT_BY_SYNC_LEVEL: Record<SourceSyncStatusLevel, 'success' | 'destructive' | 'default'> = {
    synced: 'success',
    error: 'destructive',
    disabled: 'default',
    pending: 'default',
}

const TARGET_TYPE_FILTER_OPTIONS: { value: CustomPropertyTargetTypeFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'account', label: 'Accounts' },
    { value: 'person', label: 'Persons' },
    { value: 'group', label: 'Groups' },
]

const COLUMN_COUNT = 9

function HeadWithHelp({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            {label}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={<Button size="icon-xs" aria-label={`About ${label.toLowerCase()}`} />}
                >
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{help}</TooltipContent>
            </Tooltip>
        </span>
    )
}

function MutedText({ children, tooltip }: { children: string; tooltip?: string }): JSX.Element {
    const text = (
        <Text size="xs" variant="muted" render={<span className="m-0" />}>
            {children}
        </Text>
    )

    if (!tooltip) {
        return text
    }

    return (
        <Tooltip>
            <TooltipTrigger render={text} />
            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
        </Tooltip>
    )
}

function ReferencesCell({
    hasWorkflowReference,
    references,
}: {
    hasWorkflowReference: boolean
    references: readonly CustomPropertyReferenceApi[]
}): JSX.Element {
    if (!hasWorkflowReference) {
        return <MutedText>0</MutedText>
    }

    if (!references.length) {
        return <MutedText tooltip="You don't have access to view the workflow.">Workflow</MutedText>
    }

    return (
        <Popover>
            <PopoverTrigger render={<Button variant="link" size="sm" />}>{references.length}</PopoverTrigger>
            <PopoverContent align="start" className="flex max-w-sm flex-col gap-1">
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    Used in
                </Text>
                {references.map((reference) => (
                    <Button
                        key={reference.id}
                        variant="link"
                        size="sm"
                        nativeButton={false}
                        className="justify-start"
                        render={<LinkPrimitive to={urls.workflow(reference.id, 'workflow')} target="_blank" />}
                    >
                        {reference.name}
                    </Button>
                ))}
            </PopoverContent>
        </Popover>
    )
}

export interface QuillCustomPropertiesConfigProps {
    definitions: CustomPropertyDefinitionApi[]
    loading: boolean
    searchTerm: string
    targetTypeFilter: CustomPropertyTargetTypeFilter
    restrictionReason: string | null
    hasSyncRuns: (definition: CustomPropertyDefinitionApi) => boolean
    renderSyncRuns: (definition: CustomPropertyDefinitionApi) => JSX.Element | null
    onExpand: (definition: CustomPropertyDefinitionApi) => void
    onCreate: () => void
    onEdit: (definition: CustomPropertyDefinitionApi) => void
    onDelete: (definition: CustomPropertyDefinitionApi) => void
    onSearch: (searchTerm: string) => void
    onTargetTypeFilterChange: (targetTypeFilter: CustomPropertyTargetTypeFilter) => void
}

export function QuillCustomPropertiesConfig({
    definitions,
    loading,
    searchTerm,
    targetTypeFilter,
    restrictionReason,
    hasSyncRuns,
    renderSyncRuns,
    onExpand,
    onCreate,
    onEdit,
    onDelete,
    onSearch,
    onTargetTypeFilterChange,
}: QuillCustomPropertiesConfigProps): JSX.Element {
    const [expandedIds, setExpandedIds] = useState<string[]>([])
    const [page, setPage] = useState(1)

    const pageCount = Math.max(Math.ceil(definitions.length / PAGE_SIZE), 1)
    const currentPage = Math.min(page, pageCount)
    const pageDefinitions = definitions.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE)

    const toggleExpanded = (definition: CustomPropertyDefinitionApi): void => {
        if (expandedIds.includes(definition.id)) {
            setExpandedIds(expandedIds.filter((id) => id !== definition.id))
            return
        }

        setExpandedIds([...expandedIds, definition.id])
        onExpand(definition)
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-col gap-1">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Custom properties
                    </Heading>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Define typed properties to store on your accounts.
                    </Text>
                </div>
                <Button variant="primary" onClick={onCreate} disabledReason={restrictionReason}>
                    <IconPlus />
                    New custom property
                </Button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <Input
                    type="search"
                    size="sm"
                    placeholder="Search custom properties"
                    aria-label="Search custom properties"
                    value={searchTerm}
                    onChange={(event) => onSearch(event.target.value)}
                    className="max-w-80"
                />
                <ToggleGroup
                    variant="outline"
                    aria-label="Attach to"
                    value={[targetTypeFilter]}
                    onValueChange={(next: string[]) => {
                        if (next[0]) {
                            onTargetTypeFilterChange(next[0] as CustomPropertyTargetTypeFilter)
                        }
                    }}
                >
                    {TARGET_TYPE_FILTER_OPTIONS.map((option) => (
                        <ToggleGroupItem key={option.value} value={option.value}>
                            {option.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
            {loading && definitions.length === 0 ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                </div>
            ) : (
                <Table fullWidth className="rounded-md border border-border">
                    <TableHeader>
                        <TableRow>
                            <TableHead />
                            <TableHead>Name</TableHead>
                            <TableHead>Attach to</TableHead>
                            <TableHead>Type</TableHead>
                            <TableHead expand>Description</TableHead>
                            <TableHead>
                                <HeadWithHelp
                                    label="References"
                                    help="Workflows that set this property using an 'Update account property' action. Click the count to open them."
                                />
                            </TableHead>
                            <TableHead>Last updated</TableHead>
                            <TableHead>
                                <HeadWithHelp
                                    label="Sync"
                                    help="Expand a warehouse-backed account property to see staging, retries, and account updates."
                                />
                            </TableHead>
                            <TableHead />
                        </TableRow>
                    </TableHeader>
                    {definitions.length === 0 ? (
                        <TableEmpty>
                            <Empty>
                                <EmptyHeader>
                                    <EmptyTitle>
                                        {searchTerm || targetTypeFilter !== 'all'
                                            ? 'No custom properties match your filters.'
                                            : 'No custom properties yet. Create one to get started.'}
                                    </EmptyTitle>
                                </EmptyHeader>
                            </Empty>
                        </TableEmpty>
                    ) : (
                        <TableBody>
                            {pageDefinitions.map((definition) => {
                                const expandable = hasSyncRuns(definition)
                                const isExpanded = expandable && expandedIds.includes(definition.id)
                                const canonicalReason = definition.is_canonical
                                    ? "PostHog sets this property automatically, so it can't be edited or deleted."
                                    : undefined
                                const syncStatus = definition.source ? sourceSyncStatus(definition.source) : null

                                return (
                                    <Fragment key={definition.id}>
                                        <TableRow>
                                            <TableCell>
                                                {expandable && (
                                                    <Button
                                                        size="icon-sm"
                                                        aria-label={
                                                            isExpanded ? 'Hide sync history' : 'Show sync history'
                                                        }
                                                        aria-expanded={isExpanded}
                                                        onClick={() => toggleExpanded(definition)}
                                                    >
                                                        {isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                                                    </Button>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <span className="flex items-center gap-1 font-semibold">
                                                    {definition.is_canonical && (
                                                        <Tooltip>
                                                            <TooltipTrigger
                                                                render={<span className="flex items-center" />}
                                                            >
                                                                <IconLogomark className="text-lg shrink-0" />
                                                            </TooltipTrigger>
                                                            <TooltipContent>
                                                                PostHog sets this property automatically
                                                            </TooltipContent>
                                                        </Tooltip>
                                                    )}
                                                    {definition.name}
                                                </span>
                                            </TableCell>
                                            <TableCell>
                                                {definition.target_type === 'person' ? (
                                                    <Badge variant="completed">Person</Badge>
                                                ) : definition.target_type === 'group' ? (
                                                    <Badge variant="warning">Group</Badge>
                                                ) : (
                                                    <Badge>Account</Badge>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                {/* display_type only shapes how an account property renders; a person
                                                    property is a raw $set value, so there's nothing meaningful to show for it. */}
                                                {definition.target_type === 'person' ? (
                                                    <MutedText>-</MutedText>
                                                ) : (
                                                    labelForDisplayType(definition.display_type)
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                {definition.description ? (
                                                    definition.description
                                                ) : (
                                                    <MutedText>-</MutedText>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <ReferencesCell
                                                    hasWorkflowReference={definition.has_workflow_reference}
                                                    references={definition.references}
                                                />
                                            </TableCell>
                                            <TableCell>
                                                {definition.updated_at ? (
                                                    <TZLabel time={definition.updated_at} />
                                                ) : (
                                                    <MutedText>-</MutedText>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                {definition.is_canonical ? (
                                                    <MutedText>Auto</MutedText>
                                                ) : !definition.source || !syncStatus ? (
                                                    definition.has_workflow_reference ? (
                                                        <MutedText tooltip="This property is updated by a workflow.">
                                                            Workflow
                                                        </MutedText>
                                                    ) : (
                                                        <MutedText>Manual</MutedText>
                                                    )
                                                ) : (
                                                    <Tooltip>
                                                        <TooltipTrigger
                                                            render={<span className="flex items-center gap-2" />}
                                                        >
                                                            <Badge
                                                                variant={BADGE_VARIANT_BY_SYNC_LEVEL[syncStatus.level]}
                                                            >
                                                                {syncStatus.label}
                                                            </Badge>
                                                            {syncStatus.level === 'synced' &&
                                                                definition.source.last_synced_at && (
                                                                    <Text
                                                                        size="xs"
                                                                        variant="muted"
                                                                        render={<span className="m-0" />}
                                                                    >
                                                                        <TZLabel
                                                                            time={definition.source.last_synced_at}
                                                                        />
                                                                    </Text>
                                                                )}
                                                        </TooltipTrigger>
                                                        <TooltipContent className="max-w-80">
                                                            {syncStatus.tooltip}
                                                        </TooltipContent>
                                                    </Tooltip>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex justify-end gap-1">
                                                    <Button
                                                        size="icon"
                                                        aria-label="Edit"
                                                        tooltip="Edit"
                                                        onClick={() => onEdit(definition)}
                                                        disabledReason={canonicalReason ?? restrictionReason}
                                                    >
                                                        <IconPencil />
                                                    </Button>
                                                    <Button
                                                        variant="destructive-outline"
                                                        size="icon"
                                                        aria-label="Delete"
                                                        tooltip="Delete"
                                                        onClick={() => onDelete(definition)}
                                                        disabledReason={canonicalReason ?? restrictionReason}
                                                        data-attr="delete-custom-property"
                                                    >
                                                        <IconTrash />
                                                    </Button>
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                        {isExpanded && (
                                            <TableRow>
                                                <TableCell colSpan={COLUMN_COUNT}>
                                                    {renderSyncRuns(definition)}
                                                </TableCell>
                                            </TableRow>
                                        )}
                                    </Fragment>
                                )
                            })}
                        </TableBody>
                    )}
                </Table>
            )}
            {pageCount > 1 && (
                <QuillTablePagination
                    currentPage={currentPage}
                    pageCount={pageCount}
                    pageSize={PAGE_SIZE}
                    total={definitions.length}
                    onPageChange={setPage}
                />
            )}
            <CustomPropertyModal />
        </div>
    )
}
