import type { ColumnDef } from '@tanstack/react-table'
import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useId, useMemo } from 'react'

import { IconEllipsis, IconSearch } from '@posthog/icons'
import {
    Badge,
    Button,
    Checkbox,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    Field,
    FieldLabel,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { MemberSelect } from 'lib/components/MemberSelect'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { HogFunctionType } from '~/types'

import { HogFunctionIcon } from '../configuration/HogFunctionIcon'
import { humanizeHogFunctionType } from '../hog-function-utils'
import { HogFunctionStatusIndicator } from '../misc/HogFunctionStatusIndicator'
import { HogFunctionOrderModal } from './HogFunctionOrderModal'
import { hogFunctionRequestModalLogic } from './hogFunctionRequestModalLogic'
import { getNotificationSourceOptions, urlForHogFunction } from './HogFunctionsList'
import { HogFunctionListLogicProps, hogFunctionsListLogic } from './hogFunctionsListLogic'
import { QuillNotificationContextTag } from './QuillNotificationContextTag'

const PAGE_SIZE = 30

export type QuillHogFunctionListProps = HogFunctionListLogicProps & {
    extraControls?: JSX.Element
    hideFeedback: boolean
    emptyText?: string
    onDeleteHogFunction?: (hogFunction: HogFunctionType) => void
    onEditHogFunction?: (hogFunction: HogFunctionType) => void
    returnTo?: string
    truncateDescriptions: boolean
    manualFunctionsLoading: boolean
    isManualFunction: (hogFunction: HogFunctionType) => boolean
}

export function QuillHogFunctionList({
    extraControls,
    hideFeedback,
    emptyText,
    onDeleteHogFunction,
    onEditHogFunction,
    returnTo,
    truncateDescriptions,
    manualFunctionsLoading,
    isManualFunction,
    ...props
}: QuillHogFunctionListProps): JSX.Element {
    const { loading, filteredHogFunctions, filters, sortedHogFunctions, hiddenHogFunctions, notificationSources } =
        useValues(hogFunctionsListLogic(props))
    const { setFilters, resetFilters, toggleEnabled, deleteHogFunction, setReorderModalOpen } = useActions(
        hogFunctionsListLogic(props)
    )
    const { openFeedbackDialog } = useActions(hogFunctionRequestModalLogic)
    const showPausedId = useId()

    const humanizedType = humanizeHogFunctionType(props.type)
    const isLoading = loading || manualFunctionsLoading
    const showNotificationSourceFilter = notificationSources.length > 1 || !!filters.notificationSource
    const notificationSourceOptions = getNotificationSourceOptions(notificationSources)
    const showsExecutionOrder = props.type === 'transformation' || props.type === 'transformation_log'

    const columns = useMemo<ColumnDef<HogFunctionType>[]>(() => {
        const columns: ColumnDef<HogFunctionType>[] = [
            {
                id: 'icon',
                header: '',
                enableSorting: false,
                cell: ({ row }) => <HogFunctionIcon src={row.original.icon_url} size="small" />,
            },
            {
                id: 'name',
                header: 'Name',
                accessorFn: (hogFunction) => (hogFunction.name ?? '').toLowerCase(),
                meta: { expand: true },
                cell: ({ row }) => {
                    const hogFunction = row.original

                    return (
                        <div className="flex flex-col gap-1 py-1">
                            <div className="flex flex-wrap items-center gap-1">
                                <Button
                                    variant="link-foreground"
                                    size="sm"
                                    nativeButton={false}
                                    tooltip="Click to update configuration, view metrics, and more"
                                    render={
                                        <LinkPrimitive
                                            to={urlForHogFunction(hogFunction, returnTo)}
                                            onClick={
                                                onEditHogFunction ? () => onEditHogFunction(hogFunction) : undefined
                                            }
                                        />
                                    }
                                >
                                    {hogFunction.name}
                                </Button>
                                {hogFunction.type === 'internal_destination' && (
                                    <QuillNotificationContextTag hogFunction={hogFunction} />
                                )}
                                {hogFunction.draft_updated_at && (
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={
                                                <Badge variant="warning" tabIndex={0}>
                                                    Unpublished changes
                                                </Badge>
                                            }
                                        />
                                        <TooltipContent>
                                            Staged changes are waiting to be published. Open it to review them.
                                        </TooltipContent>
                                    </Tooltip>
                                )}
                            </div>
                            {hogFunction.description ? (
                                <Text
                                    size="xs"
                                    variant="muted"
                                    render={<div className={truncateDescriptions ? 'line-clamp-2' : undefined} />}
                                >
                                    <LemonMarkdown lowKeyHeadings disableImages>
                                        {hogFunction.description}
                                    </LemonMarkdown>
                                </Text>
                            ) : null}
                        </div>
                    )
                },
            },
            {
                id: 'created_by',
                header: 'Created by',
                accessorFn: (hogFunction) => hogFunction.created_by?.first_name || hogFunction.created_by?.email || '',
                cell: ({ row }) =>
                    row.original.created_by ? (
                        <ProfilePicture user={row.original.created_by} size="md" showName />
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            -
                        </Text>
                    ),
            },
            {
                id: 'updated_at',
                header: 'Updated',
                accessorFn: (hogFunction) => new Date(hogFunction.updated_at ?? 0).getTime(),
                cell: ({ row }) =>
                    row.original.updated_at ? (
                        <TZLabel time={row.original.updated_at} />
                    ) : (
                        <Text size="xs" variant="muted" render={<span />}>
                            -
                        </Text>
                    ),
            },
            {
                id: 'metrics',
                header: 'Last 7 days',
                enableSorting: false,
                cell: ({ row }) => {
                    const hogFunction = row.original

                    if (isManualFunction(hogFunction) || hogFunction.type === 'site_app') {
                        return (
                            <Text size="xs" variant="muted" render={<span />}>
                                N/A
                            </Text>
                        )
                    }

                    return (
                        <LinkPrimitive to={urlForHogFunction(hogFunction) + '?tab=metrics'}>
                            <AppMetricsSparkline
                                logicKey={hogFunction.id}
                                forceParams={{
                                    appSource: 'hog_function',
                                    appSourceId: hogFunction.id,
                                    // Log transformations report drops and budget skips under metric_kind 'other',
                                    // so without it their sparkline reads as idle.
                                    metricKind:
                                        hogFunction.type === 'transformation_log'
                                            ? ['success', 'failure', 'other']
                                            : ['success', 'failure'],
                                    breakdownBy: 'metric_kind',
                                    interval: 'day',
                                    dateFrom: '-7d',
                                }}
                            />
                        </LinkPrimitive>
                    )
                },
            },
            {
                id: 'enabled',
                header: 'Status',
                accessorFn: (hogFunction) => (hogFunction.enabled ? 1 : 0),
                cell: ({ row }) => <HogFunctionStatusIndicator hogFunction={row.original} />,
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => {
                    const hogFunction = row.original
                    const label = `Actions for ${hogFunction.name}`

                    return (
                        <DropdownMenu>
                            <DropdownMenuTrigger render={<Button size="icon" aria-label={label} tooltip={label} />}>
                                <IconEllipsis />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                {isManualFunction(hogFunction) ? (
                                    <DropdownMenuItem
                                        onClick={() => router.actions.push(urlForHogFunction(hogFunction, returnTo))}
                                    >
                                        View & configure
                                    </DropdownMenuItem>
                                ) : (
                                    <>
                                        <DropdownMenuItem
                                            onClick={() => toggleEnabled(hogFunction, !hogFunction.enabled)}
                                        >
                                            {hogFunction.enabled ? 'Pause' : 'Unpause'}
                                        </DropdownMenuItem>
                                        <DropdownMenuItem
                                            variant="destructive"
                                            onClick={() => {
                                                onDeleteHogFunction?.(hogFunction)
                                                deleteHogFunction(hogFunction)
                                            }}
                                        >
                                            Delete
                                        </DropdownMenuItem>
                                    </>
                                )}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )
                },
            },
        ]

        if (showsExecutionOrder) {
            columns.splice(1, 0, {
                id: 'execution_order',
                header: 'Prio',
                accessorFn: (hogFunction) => hogFunction.execution_order ?? 0,
                cell: ({ row }) => (
                    <Button
                        size="sm"
                        tooltip="Transformations are executed in a specific order. Click to reorder them."
                        onClick={() => setReorderModalOpen(true)}
                    >
                        <Badge>{row.original.execution_order ?? 0}</Badge>
                    </Button>
                ),
            })
        }

        return columns
    }, [
        showsExecutionOrder,
        toggleEnabled,
        deleteHogFunction,
        setReorderModalOpen,
        isManualFunction,
        onDeleteHogFunction,
        onEditHogFunction,
        returnTo,
        truncateDescriptions,
    ])

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <InputGroup size="sm" className="grow min-w-48 max-w-80">
                    <InputGroupAddon align="inline-start">
                        <IconSearch />
                    </InputGroupAddon>
                    <InputGroupInput
                        type="search"
                        placeholder="Search..."
                        aria-label="Search"
                        value={filters.search ?? ''}
                        onChange={(event) => setFilters({ search: event.target.value })}
                    />
                </InputGroup>
                {!hideFeedback ? (
                    <Button variant="link-muted" onClick={() => openFeedbackDialog(props.type)}>
                        Can't find what you're looking for?
                    </Button>
                ) : null}
                <div className="flex flex-wrap items-center gap-2 ml-auto">
                    <div className="flex items-center gap-2">
                        <Text size="xs" render={<span />}>
                            Created by:
                        </Text>
                        <MemberSelect
                            value={filters.createdBy || null}
                            onChange={(user) => setFilters({ createdBy: user?.uuid || null })}
                        />
                    </div>
                    {showNotificationSourceFilter && (
                        <Select
                            items={notificationSourceOptions}
                            value={filters.notificationSource ?? null}
                            onValueChange={(value) => setFilters({ notificationSource: value ?? undefined })}
                        >
                            <SelectTrigger
                                aria-label="Notification source"
                                className="w-fit"
                                data-attr="hog-function-notification-source-filter"
                            >
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {notificationSourceOptions.map((option) => (
                                    <SelectItem key={option.value ?? 'all'} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    )}
                    <Field orientation="horizontal" className="w-fit">
                        <Checkbox
                            id={showPausedId}
                            checked={!!filters.showPaused}
                            onCheckedChange={(checked: boolean) => setFilters({ showPaused: checked })}
                        />
                        <FieldLabel htmlFor={showPausedId}>Show paused</FieldLabel>
                    </Field>
                    {extraControls}
                </div>
            </div>

            <BindLogic logic={hogFunctionsListLogic} props={props}>
                {isLoading && filteredHogFunctions.length === 0 ? (
                    <Skeleton className="h-40" />
                ) : (
                    <div aria-busy={isLoading}>
                        <DataTable
                            columns={columns}
                            data={filteredHogFunctions}
                            fullWidth
                            // The sparkline loads once per row, so a row must keep its function across a sort or a search.
                            getRowId={(hogFunction) => hogFunction.id}
                            pageSize={filteredHogFunctions.length > PAGE_SIZE ? PAGE_SIZE : undefined}
                            empty={
                                <Empty>
                                    <EmptyHeader>
                                        <EmptyDescription>
                                            {
                                                // The API applies the search itself, so an empty result with a search is a filter miss.
                                                sortedHogFunctions.length === 0 && !filters.search?.trim()
                                                    ? (emptyText ?? `No ${humanizedType}s found`)
                                                    : `No ${humanizedType}s matching filters.`
                                            }
                                        </EmptyDescription>
                                    </EmptyHeader>
                                    {sortedHogFunctions.length > 0 || filters.search?.trim() ? (
                                        <EmptyContent>
                                            <Button variant="outline" onClick={() => resetFilters()}>
                                                Clear filters
                                            </Button>
                                        </EmptyContent>
                                    ) : null}
                                </Empty>
                            }
                        />
                    </div>
                )}
                {hiddenHogFunctions.length > 0 && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {hiddenHogFunctions.length} hidden.{' '}
                        <Button
                            variant="link"
                            size="inline"
                            onClick={() => {
                                resetFilters()
                                setFilters({ showPaused: true })
                            }}
                        >
                            Show all
                        </Button>
                    </Text>
                )}
                <HogFunctionOrderModal />
            </BindLogic>
        </div>
    )
}
