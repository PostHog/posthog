import { type ColumnDef } from '@tanstack/react-table'
import { useMemo } from 'react'

import { IconCheck, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Heading,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { IconLink } from 'lib/lemon-ui/icons'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { formatMarketingMoney } from '../../logic/utils'
import type { CampaignAuditResult, UtmEvent } from '../../logic/utmAuditLogic'
import { QuillTableLoadingRows } from '../common/QuillTableLoadingRows'
import { QuillUtmAuditActionsMenu } from './QuillUtmAuditActionsMenu'
import { formatNumber, issueLabel, issueTooltip } from './utmAuditLabels'

export function QuillUtmAuditCampaignTab({
    loading,
    campaigns,
    utmCampaigns,
    selectedCampaign,
    selectedUtmCampaign,
    onSelectCampaign,
    onSelectUtmCampaign,
    campaignSearch,
    onCampaignSearchChange,
    utmSearch,
    onUtmSearchChange,
    baseCurrency,
    canMap,
    mapPrompt,
    onMapCampaign,
}: {
    loading: boolean
    campaigns: CampaignAuditResult[]
    utmCampaigns: UtmEvent[]
    selectedCampaign: string | null
    selectedUtmCampaign: string | null
    onSelectCampaign: (campaignName: string | null) => void
    onSelectUtmCampaign: (utmCampaign: string | null) => void
    campaignSearch: string
    onCampaignSearchChange: (search: string) => void
    utmSearch: string
    onUtmSearchChange: (search: string) => void
    baseCurrency: CurrencyCode
    canMap: boolean
    mapPrompt: string
    onMapCampaign: () => void
}): JSX.Element {
    const campaignColumns = useMemo<ColumnDef<CampaignAuditResult, unknown>[]>(
        () => [
            {
                id: 'campaign_name',
                header: 'Campaign',
                enableSorting: false,
                meta: { expand: true },
                cell: ({ row }) => (
                    <div className="flex flex-col">
                        <span className="font-medium">{row.original.campaign_name}</span>
                        <Text size="xs" variant="muted" render={<span />}>
                            {`${row.original.source_name} · ID: ${row.original.campaign_id} · ${formatMarketingMoney(row.original.spend, baseCurrency)} · ${formatNumber(row.original.clicks)} clicks`}
                        </Text>
                    </div>
                ),
            },
            {
                id: 'status',
                header: 'Status',
                enableSorting: false,
                cell: ({ row }) => {
                    const issue = row.original.issues[0]
                    if (!issue) {
                        return <Badge variant="success">OK</Badge>
                    }
                    return (
                        <Tooltip>
                            <TooltipTrigger
                                render={<Badge variant={issue.severity === 'error' ? 'destructive' : 'warning'} />}
                            >
                                <IconWarning />
                                {issueLabel(row.original)}
                            </TooltipTrigger>
                            <TooltipContent className="max-w-80">{issueTooltip(row.original)}</TooltipContent>
                        </Tooltip>
                    )
                },
            },
        ],
        [baseCurrency]
    )

    const utmColumns = useMemo<ColumnDef<UtmEvent, unknown>[]>(
        () => [
            {
                id: 'utm_campaign',
                header: 'utm_campaign',
                enableSorting: false,
                meta: { expand: true },
                cell: ({ row }) => <span className="font-mono">{row.original.utm_campaign}</span>,
            },
            {
                id: 'utm_source',
                header: 'utm_source',
                enableSorting: false,
                cell: ({ row }) => <span className="font-mono text-muted-foreground">{row.original.utm_source}</span>,
            },
            {
                id: 'event_count',
                header: 'Pageviews',
                enableSorting: false,
                cell: ({ row }) => formatNumber(row.original.event_count),
            },
            {
                id: 'match',
                header: '',
                enableSorting: false,
                cell: ({ row }) => {
                    if (row.original.campaign_match === 'auto') {
                        return (
                            <Tooltip>
                                <TooltipTrigger render={<span className="inline-flex" />}>
                                    <IconCheck className="size-4 text-success-foreground" />
                                </TooltipTrigger>
                                <TooltipContent>{`Auto-matched to: ${row.original.matched_campaign}`}</TooltipContent>
                            </Tooltip>
                        )
                    }
                    if (row.original.campaign_match === 'mapped') {
                        return (
                            <Tooltip>
                                <TooltipTrigger render={<span className="inline-flex" />}>
                                    <IconLink className="size-4 text-primary" />
                                </TooltipTrigger>
                                <TooltipContent>{`Manually mapped to: ${row.original.matched_campaign}`}</TooltipContent>
                            </Tooltip>
                        )
                    }
                    return null
                },
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                cell: ({ row }) => <QuillUtmAuditActionsMenu columnName="Campaign" value={row.original.utm_campaign} />,
            },
        ],
        []
    )

    return (
        <div className="@container flex flex-col gap-4">
            <div
                data-quill
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3"
            >
                <Text size="xs" variant="muted" render={<div />}>
                    {mapPrompt}
                </Text>
                <Button variant="primary" onClick={onMapCampaign} disabledReason={canMap ? undefined : mapPrompt}>
                    Map campaign
                </Button>
            </div>

            <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-2">
                <div className="flex min-w-0 flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Heading size="sm" render={<h4 className="m-0" />}>
                            Ad platform campaigns
                        </Heading>
                        <AnalyticsSearchInput
                            value={campaignSearch}
                            onChange={onCampaignSearchChange}
                            label="Search ad platform campaigns"
                            placeholder="Search..."
                            dataAttr="marketing-utm-audit-ad-campaign-search"
                            className="w-48 max-w-full"
                        />
                    </div>
                    <div className={cn('transition-opacity', loading && 'opacity-60')} aria-busy={loading || undefined}>
                        <DataTable
                            className="max-h-150"
                            stickyHeader
                            fullWidth
                            size="sm"
                            columns={campaignColumns}
                            data={campaigns}
                            getRowId={(record) => `${record.source_name}-${record.campaign_id}`}
                            onRowClick={(record) => onSelectCampaign(record.campaign_name)}
                            rowClassName={(record) =>
                                record.campaign_name === selectedCampaign ? 'bg-fill-selected' : undefined
                            }
                            empty={
                                loading ? (
                                    <QuillTableLoadingRows />
                                ) : (
                                    <Empty>
                                        <EmptyHeader>
                                            <EmptyDescription>No campaigns found</EmptyDescription>
                                        </EmptyHeader>
                                    </Empty>
                                )
                            }
                        />
                    </div>
                </div>

                <div className="flex min-w-0 flex-col gap-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Heading size="sm" render={<h4 className="m-0" />}>
                            UTM campaigns
                        </Heading>
                        <AnalyticsSearchInput
                            value={utmSearch}
                            onChange={onUtmSearchChange}
                            label="Search UTM campaigns"
                            placeholder="Search..."
                            dataAttr="marketing-utm-audit-utm-campaign-search"
                            className="w-48 max-w-full"
                        />
                    </div>
                    <div className={cn('transition-opacity', loading && 'opacity-60')} aria-busy={loading || undefined}>
                        <DataTable
                            className="max-h-150"
                            stickyHeader
                            fullWidth
                            size="sm"
                            columns={utmColumns}
                            data={utmCampaigns}
                            getRowId={(record) => `${record.utm_campaign}-${record.utm_source}`}
                            onRowClick={(record) => onSelectUtmCampaign(record.utm_campaign)}
                            rowClassName={(record) =>
                                record.utm_campaign === selectedUtmCampaign ? 'bg-fill-selected' : undefined
                            }
                            empty={
                                loading ? (
                                    <QuillTableLoadingRows />
                                ) : (
                                    <Empty>
                                        <EmptyHeader>
                                            <EmptyDescription>No UTM events found</EmptyDescription>
                                        </EmptyHeader>
                                    </Empty>
                                )
                            }
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}
