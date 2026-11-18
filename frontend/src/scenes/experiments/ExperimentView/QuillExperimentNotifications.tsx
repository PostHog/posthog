import { useActions, useValues } from 'kea'
import { type ReactNode, useState } from 'react'

import { IconEllipsis, IconMegaphone, IconPlusSmall } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    Checkbox,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Field,
    Label,
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
import type { DataTableProps } from '@posthog/quill'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'
import { QuillTimeCell } from 'lib/components/QuillTableCells/QuillTableCells'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { fullName } from 'lib/utils/strings'
import { AnalyticsOwner, AnalyticsOwnerAvatar } from 'scenes/analytics/AnalyticsOwner'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'
import { getHogFunctionDeliveryType } from 'scenes/hog-functions/hog-function-utils'
import { hogFunctionRequestModalLogic } from 'scenes/hog-functions/list/hogFunctionRequestModalLogic'
import { urlForHogFunction } from 'scenes/hog-functions/list/HogFunctionsList'
import { hogFunctionsListLogic } from 'scenes/hog-functions/list/hogFunctionsListLogic'
import { hogFunctionTemplateListLogic } from 'scenes/hog-functions/list/hogFunctionTemplateListLogic'
import { DisplayOptions, hogFunctionStatusDisplay } from 'scenes/hog-functions/misc/HogFunctionStatusIndicator'

import { membersLogic } from '~/models/membersLogic'
import { CyclotronJobFiltersType, HogFunctionTemplateType, HogFunctionType } from '~/types'

import {
    EXPERIMENT_NOTIFICATION_SUB_TEMPLATES,
    NOTIFICATIONS_DESCRIPTION,
    NOTIFICATIONS_TITLE,
} from './experimentNotificationsModel'
import { QuillSectionHeading } from './QuillCardParts'

const ANY_USER = '__any__'
const ALL_DELIVERY_TYPES = '__all__'
const NOTIFICATIONS_PAGE_SIZE = 30
const FEEDBACK_LINK_LABEL = "Can't find what you're looking for?"

type BadgeVariant = 'default' | 'info' | 'warning' | 'success' | 'completed' | 'destructive'

const STATUS_BADGE_VARIANT: Partial<Record<NonNullable<DisplayOptions['tagType']>, BadgeVariant>> = {
    success: 'success',
    caution: 'warning',
    warning: 'warning',
    danger: 'destructive',
}

const TEMPLATE_STATUS_BADGE: Partial<Record<string, { label: string; variant: BadgeVariant }>> = {
    alpha: { label: 'Experimental', variant: 'destructive' },
    beta: { label: 'Beta', variant: 'completed' },
    coming_soon: { label: 'Roadmap', variant: 'default' },
    hidden: { label: 'Hidden', variant: 'default' },
}

function BadgeWithTooltip({
    variant,
    tooltip,
    children,
}: {
    variant: BadgeVariant
    tooltip: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<Badge variant={variant} tabIndex={0} />}>{children}</TooltipTrigger>
            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
        </Tooltip>
    )
}

function NameCell({
    to,
    name,
    description,
    badges,
}: {
    to: string | undefined
    name: string
    description?: ReactNode
    badges?: ReactNode
}): JSX.Element {
    return (
        <div className="flex min-w-60 flex-col gap-0.5">
            <span className="flex flex-wrap items-center gap-1.5">
                {to ? (
                    <Button
                        variant="link-foreground"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={to} />}
                    >
                        {name}
                    </Button>
                ) : (
                    <Text size="sm" weight="semibold">
                        {name}
                    </Text>
                )}
                {badges}
            </span>
            {description && (
                <Text size="xs" variant="muted">
                    {description}
                </Text>
            )}
        </div>
    )
}

function FeedbackLink({ type }: { type: HogFunctionType['type'] }): JSX.Element {
    const { openFeedbackDialog } = useActions(hogFunctionRequestModalLogic)
    return (
        <Button variant="link-muted" size="sm" onClick={() => openFeedbackDialog(type)}>
            {FEEDBACK_LINK_LABEL}
        </Button>
    )
}

function StatusBadge({ hogFunction }: { hogFunction: HogFunctionType }): JSX.Element | null {
    const status = hogFunctionStatusDisplay(hogFunction)
    if (!status) {
        return null
    }
    return (
        <BadgeWithTooltip
            variant={STATUS_BADGE_VARIANT[status.tagType ?? 'default'] ?? 'default'}
            tooltip={status.description}
        >
            {status.display}
        </BadgeWithTooltip>
    )
}

function CreatedBySelect({
    value,
    onChange,
}: {
    value: string | null
    onChange: (uuid: string | null) => void
}): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const options = meFirstMembers.map((member) => ({
        value: member.user.uuid,
        label: fullName(member.user) || member.user.email,
        user: member.user,
    }))

    return (
        <Select
            value={value ?? ANY_USER}
            onValueChange={(next: string | null) => onChange(!next || next === ANY_USER ? null : next)}
            onOpenChange={(open: boolean) => open && ensureAllMembersLoaded()}
        >
            <SelectTrigger size="sm" data-attr="experiment-notifications-created-by">
                <SelectValue>
                    {(current: string) =>
                        `Created by: ${options.find((option) => option.value === current)?.label ?? 'Any user'}`
                    }
                </SelectValue>
            </SelectTrigger>
            <SelectContent>
                <SelectItem value={ANY_USER}>Any user</SelectItem>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        <span className="flex items-center gap-2">
                            <AnalyticsOwnerAvatar owner={option.user} />
                            {option.label}
                        </span>
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

function NotificationsList({
    forceFilterGroups,
    returnTo,
    onNew,
}: {
    forceFilterGroups: CyclotronJobFiltersType[]
    returnTo: string
    onNew: () => void
}): JSX.Element {
    const logicProps = { forceFilterGroups, type: 'internal_destination' as const }
    const { loading, filteredHogFunctions, filters, sortedHogFunctions, hiddenHogFunctions } = useValues(
        hogFunctionsListLogic(logicProps)
    )
    const { loadHogFunctions, setFilters, resetFilters, toggleEnabled, deleteHogFunction } = useActions(
        hogFunctionsListLogic(logicProps)
    )
    useOnMountEffect(loadHogFunctions)

    const columns: DataTableProps<HogFunctionType, unknown>['columns'] = [
        {
            id: 'icon',
            header: '',
            enableSorting: false,
            cell: ({ row: { original } }) => <HogFunctionIcon src={original.icon_url} size="small" />,
        },
        {
            id: 'name',
            header: 'Name',
            meta: { expand: true },
            accessorFn: (hogFunction) => hogFunction.name ?? '',
            cell: ({ row: { original } }) => (
                <NameCell
                    to={urlForHogFunction(original, returnTo)}
                    name={original.name}
                    description={original.description}
                    badges={
                        original.draft_updated_at ? (
                            <BadgeWithTooltip
                                variant="warning"
                                tooltip="Staged changes are waiting to be published. Open it to review them."
                            >
                                Unpublished changes
                            </BadgeWithTooltip>
                        ) : null
                    }
                />
            ),
        },
        {
            id: 'created_by',
            header: 'Created by',
            accessorFn: (hogFunction) => hogFunction.created_by?.first_name || hogFunction.created_by?.email || '',
            cell: ({ row: { original } }) => <AnalyticsOwner owner={original.created_by ?? null} />,
        },
        {
            id: 'updated_at',
            header: 'Updated',
            accessorFn: (hogFunction) => hogFunction.updated_at,
            cell: ({ row: { original } }) => <QuillTimeCell time={original.updated_at} />,
        },
        {
            id: 'metrics',
            header: 'Last 7 days',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <LinkPrimitive to={urlForHogFunction(original) + '?tab=metrics'}>
                    <AppMetricsSparkline
                        logicKey={original.id}
                        forceParams={{
                            appSource: 'hog_function',
                            appSourceId: original.id,
                            metricKind: ['success', 'failure'],
                            breakdownBy: 'metric_kind',
                            interval: 'day',
                            dateFrom: '-7d',
                        }}
                    />
                </LinkPrimitive>
            ),
        },
        {
            id: 'status',
            header: 'Status',
            accessorFn: (hogFunction) => (hogFunction.enabled ? 1 : -1),
            cell: ({ row: { original } }) => <StatusBadge hogFunction={original} />,
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row: { original } }) => (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon-sm"
                                aria-label={`Actions for ${original.name}`}
                                data-attr="experiment-notification-row-menu"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => toggleEnabled(original, !original.enabled)}>
                            {original.enabled ? 'Pause' : 'Unpause'}
                        </DropdownMenuItem>
                        <DropdownMenuItem variant="destructive" onClick={() => deleteHogFunction(original)}>
                            Delete
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            ),
        },
    ]

    const hasSearch = !!filters.search?.trim()

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <AnalyticsSearchInput
                    value={filters.search ?? ''}
                    onChange={(search) => setFilters({ search })}
                    label="Search notifications"
                    placeholder="Search..."
                    dataAttr="experiment-notifications-search"
                />
                <FeedbackLink type="internal_destination" />
                <div className="flex-1" />
                <CreatedBySelect
                    value={filters.createdBy || null}
                    onChange={(uuid) => setFilters({ createdBy: uuid })}
                />
                <Field orientation="horizontal" className="w-auto">
                    <Checkbox
                        id="experiment-notifications-show-paused"
                        checked={!!filters.showPaused}
                        onCheckedChange={(checked: boolean) => setFilters({ showPaused: checked })}
                    />
                    <Label htmlFor="experiment-notifications-show-paused">Show paused</Label>
                </Field>
                <Button variant="primary" size="sm" onClick={onNew}>
                    New notification
                </Button>
            </div>
            <Card size="sm" flush className="pt-0">
                <DataTable
                    columns={columns}
                    data={filteredHogFunctions}
                    fullWidth
                    size="sm"
                    pageSize={NOTIFICATIONS_PAGE_SIZE}
                    getRowId={(hogFunction) => hogFunction.id}
                    empty={
                        loading ? (
                            <Skeleton className="h-6 w-full" />
                        ) : sortedHogFunctions.length === 0 && !hasSearch ? (
                            <Text size="xs" variant="muted">
                                No notifications found
                            </Text>
                        ) : (
                            <Text size="xs" variant="muted">
                                No notifications matching filters.{' '}
                                <Button variant="link" size="inline" onClick={() => resetFilters()}>
                                    Clear filters
                                </Button>
                            </Text>
                        )
                    }
                />
                {hiddenHogFunctions.length > 0 && (
                    <Text size="xs" variant="muted" render={<div className="px-3 py-2" />}>
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
            </Card>
        </div>
    )
}

function NotificationTemplates({
    forceFilterGroups,
    returnTo,
    onCancel,
}: {
    forceFilterGroups: CyclotronJobFiltersType[]
    returnTo: string
    onCancel: () => void
}): JSX.Element {
    const logicProps = {
        type: 'destination' as const,
        subTemplateIds: EXPERIMENT_NOTIFICATION_SUB_TEMPLATES,
        getConfigurationOverrides: () => ({ filters: forceFilterGroups[0] }),
        queryParams: { returnTo },
    }
    const { loading, filteredTemplates, filters, templates, urlForTemplate, hasMultipleDeliveryTypes } = useValues(
        hogFunctionTemplateListLogic(logicProps)
    )
    const { loadHogFunctionTemplates, setFilters, resetFilters, registerInterest } = useActions(
        hogFunctionTemplateListLogic(logicProps)
    )
    useOnMountEffect(loadHogFunctionTemplates)

    const columns: DataTableProps<HogFunctionTemplateType, unknown>['columns'] = [
        {
            id: 'icon',
            header: '',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <HogFunctionIcon src={original.icon_url} className={original.icon_class_name} size="small" />
            ),
        },
        {
            id: 'name',
            header: 'Name',
            meta: { expand: true },
            accessorFn: (template) => template.name ?? '',
            cell: ({ row: { original } }) => {
                const status = original.status ? TEMPLATE_STATUS_BADGE[original.status] : undefined
                return (
                    <NameCell
                        to={urlForTemplate(original) ?? undefined}
                        name={original.name}
                        description={original.description}
                        badges={status ? <Badge variant={status.variant}>{status.label}</Badge> : null}
                    />
                )
            },
        },
        ...(hasMultipleDeliveryTypes
            ? [
                  {
                      id: 'delivery',
                      header: 'Type',
                      enableSorting: false,
                      cell: ({ row: { original } }: { row: { original: HogFunctionTemplateType } }) =>
                          getHogFunctionDeliveryType(original) === 'batch' ? (
                              <Badge variant="completed">Batch</Badge>
                          ) : (
                              <Badge variant="info">Realtime</Badge>
                          ),
                  },
              ]
            : []),
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row: { original } }) =>
                original.status === 'coming_soon' ? (
                    <Button
                        variant="primary"
                        size="sm"
                        data-attr="request-destination"
                        onClick={() => registerInterest(original)}
                    >
                        <IconMegaphone />
                        Notify me
                    </Button>
                ) : (
                    <Button
                        variant="primary"
                        size="sm"
                        data-attr="new-destination"
                        nativeButton={false}
                        render={<LinkPrimitive to={urlForTemplate(original) ?? undefined} />}
                    >
                        <IconPlusSmall />
                        Create
                    </Button>
                ),
        },
    ]

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <AnalyticsSearchInput
                    value={filters.search ?? ''}
                    onChange={(search) => setFilters({ search })}
                    label="Search destinations"
                    placeholder="Search..."
                    dataAttr="experiment-notification-templates-search"
                />
                <FeedbackLink type="destination" />
                <div className="flex-1" />
                {hasMultipleDeliveryTypes && (
                    <Select
                        value={filters.deliveryType ?? ALL_DELIVERY_TYPES}
                        onValueChange={(next: string | null) =>
                            setFilters({
                                deliveryType:
                                    !next || next === ALL_DELIVERY_TYPES
                                        ? undefined
                                        : (next as NonNullable<typeof filters.deliveryType>),
                            })
                        }
                    >
                        <SelectTrigger size="sm">
                            <SelectValue>
                                {(current: string) =>
                                    current === 'batch' ? 'Batch' : current === 'realtime' ? 'Realtime' : 'All types'
                                }
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value={ALL_DELIVERY_TYPES}>All types</SelectItem>
                            <SelectItem value="realtime">Realtime</SelectItem>
                            <SelectItem value="batch">Batch</SelectItem>
                        </SelectContent>
                    </Select>
                )}
                <Button variant="outline" size="sm" onClick={onCancel}>
                    Cancel
                </Button>
            </div>
            <Card size="sm" flush className="pt-0">
                <DataTable
                    columns={columns}
                    data={filteredTemplates}
                    fullWidth
                    size="sm"
                    getRowId={(template) => template.id}
                    empty={
                        loading ? (
                            <Skeleton className="h-6 w-full" />
                        ) : templates.length === 0 ? (
                            <Text size="xs" variant="muted">
                                No results found
                            </Text>
                        ) : (
                            <Text size="xs" variant="muted">
                                Nothing found matching filters.{' '}
                                <Button variant="link" size="inline" onClick={() => resetFilters()}>
                                    Clear filters
                                </Button>
                            </Text>
                        )
                    }
                />
            </Card>
        </div>
    )
}

export function QuillExperimentNotifications({
    forceFilterGroups,
    returnTo,
}: {
    forceFilterGroups: CyclotronJobFiltersType[]
    returnTo: string
}): JSX.Element {
    const [showTemplates, setShowTemplates] = useState(false)

    return (
        <section className="flex flex-col gap-3" data-attr="experiment-notifications">
            <div className="flex flex-col gap-1">
                <QuillSectionHeading>{NOTIFICATIONS_TITLE}</QuillSectionHeading>
                <Text size="xs" variant="muted">
                    {NOTIFICATIONS_DESCRIPTION}
                </Text>
            </div>
            {showTemplates ? (
                <NotificationTemplates
                    forceFilterGroups={forceFilterGroups}
                    returnTo={returnTo}
                    onCancel={() => setShowTemplates(false)}
                />
            ) : (
                <NotificationsList
                    forceFilterGroups={forceFilterGroups}
                    returnTo={returnTo}
                    onNew={() => setShowTemplates(true)}
                />
            )}
        </section>
    )
}
