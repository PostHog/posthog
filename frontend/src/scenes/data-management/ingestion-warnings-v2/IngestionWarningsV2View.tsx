import { useActions, useValues } from 'kea'

import * as readingIsMagicPng from '@posthog/brand/hoggies/png/reading-is-magic'
import { IconOpenSidebar, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { JSONViewer } from 'lib/components/JSONViewer'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { Sparkline } from 'lib/components/Sparkline'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import type { LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import {
    WARNING_TYPE_RENDERER,
    WARNING_TYPE_TO_DESCRIPTION,
    WARNING_TYPE_TO_DOCS_ANCHOR,
} from '../ingestion-warnings/IngestionWarningsView'
import {
    IngestionWarningV2Sample,
    IngestionWarningV2Summary,
    IngestionWarningsOrderBy,
    IngestionWarningsTimeWindow,
    ingestionWarningsV2Logic,
} from './ingestionWarningsV2Logic'

const HedgehogReadingIsMagic = pngHoggie(readingIsMagicPng)

const SEVERITY_TO_TAG_TYPE: Record<string, LemonTagType> = {
    error: 'danger',
    warning: 'warning',
    info: 'default',
}

const SEVERITY_BAR_COLORS: Record<string, string> = {
    error: 'bg-danger',
    warning: 'bg-warning',
    info: 'bg-brand-blue',
}

function EntityChip({ label, value, to }: { label: string; value: string | null; to?: string }): JSX.Element | null {
    if (!value) {
        return null
    }
    return (
        <span className="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-xs whitespace-nowrap">
            <span className="text-muted">{label}</span>
            {to ? (
                <Link to={to} className="max-w-60 truncate">
                    {value}
                </Link>
            ) : (
                <CopyToClipboardInline explicitValue={value} description={label} iconSize="xsmall">
                    <span className="max-w-60 truncate">{value}</span>
                </CopyToClipboardInline>
            )}
        </span>
    )
}

function SampleEntityChips({ sample }: { sample: IngestionWarningV2Sample }): JSX.Element | null {
    if (!sample.distinct_id && !sample.person_id && !sample.event_uuid && !sample.group_key) {
        return null
    }
    return (
        <div className="flex flex-wrap gap-1">
            <EntityChip
                label="distinct_id"
                value={sample.distinct_id}
                to={sample.distinct_id ? urls.personByDistinctId(sample.distinct_id) : undefined}
            />
            <EntityChip
                label="person_id"
                value={sample.person_id}
                to={sample.person_id ? urls.personByUUID(sample.person_id) : undefined}
            />
            <EntityChip
                label="event_uuid"
                value={sample.event_uuid}
                to={sample.event_uuid ? urls.event(sample.event_uuid, sample.timestamp) : undefined}
            />
            <EntityChip label="group_key" value={sample.group_key} />
        </div>
    )
}

function SeverityIndicator({ severity, onClick }: { severity: string; onClick?: () => void }): JSX.Element {
    return (
        <Tooltip title={onClick ? `Only show ${severity} warnings` : severity.toUpperCase()}>
            <div className="flex items-center gap-2">
                <div className={cn('w-1 h-4 rounded-full', SEVERITY_BAR_COLORS[severity] ?? 'bg-muted')} />
                <LemonTag type={SEVERITY_TO_TAG_TYPE[severity] ?? 'muted'} onClick={onClick} forceClickable={!!onClick}>
                    {severity}
                </LemonTag>
            </div>
        </Tooltip>
    )
}

function SummaryTiles(): JSX.Element {
    const { summaryStats, filters } = useValues(ingestionWarningsV2Logic)
    const { setFilters } = useActions(ingestionWarningsV2Logic)

    const severities = ['error', 'warning', 'info']
    return (
        <div className="flex flex-wrap gap-2">
            <div className="flex flex-col gap-0.5 rounded border px-3 py-2 min-w-30">
                <span className="text-muted text-xs">Warnings in window</span>
                <span className="text-lg font-semibold">{humanFriendlyNumber(summaryStats.totalCount)}</span>
            </div>
            {severities.map((severity) => {
                const count = summaryStats.bySeverity[severity]
                if (count === undefined && filters.severity !== severity) {
                    return null
                }
                const isActive = filters.severity === severity
                return (
                    <button
                        key={severity}
                        type="button"
                        className={cn(
                            'flex flex-col gap-0.5 rounded border px-3 py-2 min-w-30 text-left cursor-pointer',
                            isActive && 'border-accent'
                        )}
                        onClick={() => setFilters({ severity: isActive ? null : severity })}
                    >
                        <span className="flex items-center gap-1.5 text-muted text-xs">
                            <span className={cn('w-1 h-3 rounded-full', SEVERITY_BAR_COLORS[severity] ?? 'bg-muted')} />
                            {severity}
                        </span>
                        <span className="text-lg font-semibold">{humanFriendlyNumber(count ?? 0)}</span>
                    </button>
                )
            })}
        </div>
    )
}

function ActiveFilterTags(): JSX.Element | null {
    const { filters } = useValues(ingestionWarningsV2Logic)
    const { setFilters } = useActions(ingestionWarningsV2Logic)

    if (!filters.category && !filters.severity) {
        return null
    }
    return (
        <div className="flex items-center gap-1 text-muted text-xs">
            Filtered by:
            {filters.category && (
                <LemonTag type="highlight" closable onClose={() => setFilters({ category: null })}>
                    category: {filters.category}
                </LemonTag>
            )}
            {filters.severity && (
                <LemonTag
                    type={SEVERITY_TO_TAG_TYPE[filters.severity] ?? 'muted'}
                    closable
                    onClose={() => setFilters({ severity: null })}
                >
                    severity: {filters.severity}
                </LemonTag>
            )}
        </div>
    )
}

export function IngestionWarningsV2View(): JSX.Element {
    const { warnings, warningsLoading, summaryDatasets, bucketLabels, filters, showProductIntro } =
        useValues(ingestionWarningsV2Logic)
    const { setFilters, loadWarnings } = useActions(ingestionWarningsV2Logic)

    return (
        <SceneContent data-attr="ingestion-warnings-v2">
            <SceneTitleSection
                name="Event ingestion warnings v2"
                description="Structured ingestion warnings with category and severity, over a selectable time range."
                resourceType={{ type: 'ingestion_warning' }}
            />
            {showProductIntro ? (
                <ProductIntroduction
                    productName="Ingestion warnings"
                    thingName="ingestion warning"
                    productKey={ProductKey.INGESTION_WARNINGS}
                    isEmpty={true}
                    titleOverride={`Nice! No ingestion warnings in the past ${filters.window}`}
                    description="Your incoming events look clean. If we detect any issues with your data, we'll show them here."
                    docsURL="https://posthog.com/docs/data/data-management#ingestion-warnings"
                    customHog={HedgehogReadingIsMagic}
                    actionElementOverride={
                        <LemonButton
                            type="primary"
                            to={urls.eventDefinitions()}
                            data-attr="ingestion-warnings-v2-empty-state-events"
                            sideIcon={<IconOpenSidebar className="w-4 h-4" />}
                        >
                            Explore your events
                        </LemonButton>
                    }
                />
            ) : (
                <SceneSection>
                    <SummaryTiles />
                    <div className="flex gap-2">
                        <LemonInput
                            fullWidth
                            value={filters.q}
                            onChange={(q) => setFilters({ q })}
                            type="search"
                            placeholder="Try pasting a person or session id or an ingestion warning type"
                        />
                        <LemonSegmentedButton
                            value={filters.window}
                            onChange={(value) => setFilters({ window: value as IngestionWarningsTimeWindow })}
                            options={[
                                { value: '24h', label: '24h' },
                                { value: '7d', label: '7d' },
                                { value: '30d', label: '30d' },
                            ]}
                        />
                        <LemonButton
                            icon={<IconRefresh />}
                            type="secondary"
                            onClick={() => loadWarnings()}
                            loading={warningsLoading}
                            tooltip="Refresh"
                        />
                    </div>
                    <ActiveFilterTags />
                    <LemonTable
                        dataSource={warnings}
                        loading={warningsLoading}
                        useURLForSorting={false}
                        noSortingCancellation
                        sorting={{ columnKey: filters.orderBy, order: -1 }}
                        onSort={(newSorting) => {
                            if (
                                newSorting &&
                                (newSorting.columnKey === 'count' || newSorting.columnKey === 'last_seen')
                            ) {
                                setFilters({ orderBy: newSorting.columnKey as IngestionWarningsOrderBy })
                            }
                        }}
                        columns={[
                            {
                                title: 'Severity',
                                dataIndex: 'severity',
                                width: 0,
                                render: function Render(_, summary: IngestionWarningV2Summary) {
                                    return (
                                        <SeverityIndicator
                                            severity={summary.severity}
                                            onClick={() => setFilters({ severity: summary.severity })}
                                        />
                                    )
                                },
                            },
                            {
                                title: 'Warning',
                                dataIndex: 'type',
                                render: function Render(_, summary: IngestionWarningV2Summary) {
                                    const description = WARNING_TYPE_TO_DESCRIPTION[summary.type]
                                    const docsAnchor = WARNING_TYPE_TO_DOCS_ANCHOR[summary.type]
                                    const docsUrl = docsAnchor
                                        ? `https://posthog.com/docs/data/ingestion-warnings#${docsAnchor}`
                                        : 'https://posthog.com/docs/data/ingestion-warnings'
                                    return (
                                        <div className="flex flex-col gap-0.5 py-1">
                                            <span className="font-mono text-xs font-semibold">{summary.type}</span>
                                            <span className="text-muted text-xs">
                                                {description ? `${description} — ` : ''}
                                                <Link to={docsUrl}>docs</Link>
                                            </span>
                                        </div>
                                    )
                                },
                            },
                            {
                                title: 'Category',
                                dataIndex: 'category',
                                width: 0,
                                render: function Render(_, summary: IngestionWarningV2Summary) {
                                    return (
                                        <Tooltip title={`Only show ${summary.category} warnings`}>
                                            <LemonTag
                                                type="highlight"
                                                onClick={() => setFilters({ category: summary.category })}
                                                forceClickable
                                            >
                                                {summary.category}
                                            </LemonTag>
                                        </Tooltip>
                                    )
                                },
                            },
                            {
                                title: 'Graph',
                                width: 160,
                                render: function Render(_, summary: IngestionWarningV2Summary) {
                                    return (
                                        <div className="w-40">
                                            <Sparkline
                                                className="h-8 w-full"
                                                labels={bucketLabels}
                                                data={summaryDatasets[summary.type]}
                                            />
                                        </div>
                                    )
                                },
                            },
                            {
                                title: 'Events',
                                dataIndex: 'count',
                                key: 'count',
                                align: 'right',
                                sorter: true,
                                render: function Render(_, summary: IngestionWarningV2Summary) {
                                    return <>{humanFriendlyNumber(summary.count)}</>
                                },
                            },
                            {
                                title: 'Last Seen',
                                dataIndex: 'last_seen',
                                key: 'last_seen',
                                align: 'right',
                                sorter: true,
                                render: function Render(_, summary: IngestionWarningV2Summary) {
                                    return (
                                        <span className="font-mono text-xs whitespace-nowrap">
                                            <TZLabel time={summary.last_seen} showSeconds />
                                        </span>
                                    )
                                },
                            },
                        ]}
                        expandable={{
                            expandedRowRender: RenderSamples,
                        }}
                    />
                </SceneSection>
            )}
        </SceneContent>
    )
}

function RenderSamples(summary: IngestionWarningV2Summary): JSX.Element {
    return (
        <LemonTable
            dataSource={summary.samples}
            rowKey={(sample) => `${sample.timestamp}-${sample.event_uuid ?? ''}`}
            size="small"
            columns={[
                {
                    key: 'severity_bar',
                    width: 0,
                    render: function Render() {
                        return (
                            <div
                                className={cn(
                                    'w-1 h-4 rounded-full',
                                    SEVERITY_BAR_COLORS[summary.severity] ?? 'bg-muted'
                                )}
                            />
                        )
                    },
                },
                {
                    title: 'Time',
                    dataIndex: 'timestamp',
                    width: 0,
                    render: function Render(_, sample: IngestionWarningV2Sample) {
                        return (
                            <span className="font-mono text-xs whitespace-nowrap">
                                <TZLabel time={sample.timestamp} showSeconds />
                            </span>
                        )
                    },
                },
                {
                    title: 'Step',
                    dataIndex: 'pipeline_step',
                    width: 0,
                    render: function Render(_, sample: IngestionWarningV2Sample) {
                        return sample.pipeline_step !== 'unknown' ? (
                            <span className="font-mono text-xs text-muted whitespace-nowrap">
                                {sample.pipeline_step}
                            </span>
                        ) : null
                    },
                },
                {
                    title: 'Description',
                    key: 'description',
                    render: function Render(_, sample: IngestionWarningV2Sample) {
                        const renderer = WARNING_TYPE_RENDERER[summary.type as keyof typeof WARNING_TYPE_RENDERER]
                        return (
                            <div className="flex flex-col gap-1 py-1">
                                <SampleEntityChips sample={sample} />
                                {renderer ? (
                                    <div className="text-xs">
                                        {renderer({
                                            type: summary.type,
                                            timestamp: sample.timestamp,
                                            details: sample.details,
                                        })}
                                    </div>
                                ) : (
                                    <span className="font-mono text-xs text-muted break-all">
                                        {JSON.stringify(sample.details)}
                                    </span>
                                )}
                            </div>
                        )
                    },
                },
            ]}
            expandable={{
                expandedRowRender: function RenderSampleDetails(sample: IngestionWarningV2Sample) {
                    return (
                        <div className="p-2 bg-primary border-t border-border font-mono text-xs">
                            <JSONViewer src={sample.details} name="details" collapsed={false} />
                        </div>
                    )
                },
            }}
            embedded
            showHeader={false}
            pagination={{
                pageSize: 20,
            }}
        />
    )
}
