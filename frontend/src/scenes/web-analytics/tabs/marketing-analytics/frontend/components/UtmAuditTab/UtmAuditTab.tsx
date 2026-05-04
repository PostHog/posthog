import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconEllipsis, IconWarning } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTabs,
    LemonTag,
    Popover,
    Tooltip,
} from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'

import {
    MARKETING_INTEGRATION_CONFIGS,
    NativeMarketingSource,
    VALID_NATIVE_MARKETING_SOURCES,
} from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import type { AggregatedUtmSource, CampaignAuditResult, HealthTab, UtmEvent } from '../../logic/utmAuditLogic'
import { utmAuditLogic } from '../../logic/utmAuditLogic'
import { NonIntegratedConversionsCellActions } from '../NonIntegratedConversionsTable/NonIntegratedConversionsCellActions'
import { CampaignFieldPreferencesConfiguration } from '../settings/CampaignFieldPreferencesConfiguration'
import { CampaignNameMappingsConfiguration } from '../settings/CampaignNameMappingsConfiguration'
import { CustomSourceMappingsConfiguration } from '../settings/CustomSourceMappingsConfiguration'
import { IntegrationSettingsModal } from '../settings/IntegrationSettingsModal'

const SOURCE_TO_INTEGRATION: Record<string, NativeMarketingSource> = Object.fromEntries(
    VALID_NATIVE_MARKETING_SOURCES.map((source) => [MARKETING_INTEGRATION_CONFIGS[source].primarySource, source])
)

const DISPLAY_NAMES: Record<string, string> = {
    google: 'Google Ads',
    meta: 'Meta Ads',
    linkedin: 'LinkedIn Ads',
    tiktok: 'TikTok Ads',
    reddit: 'Reddit Ads',
    bing: 'Bing Ads',
    snapchat: 'Snapchat Ads',
    pinterest: 'Pinterest Ads',
    GoogleAds: 'Google Ads',
    MetaAds: 'Meta Ads',
    LinkedinAds: 'LinkedIn Ads',
    TikTokAds: 'TikTok Ads',
    RedditAds: 'Reddit Ads',
    BingAds: 'Bing Ads',
    SnapchatAds: 'Snapchat Ads',
    PinterestAds: 'Pinterest Ads',
}

function sourceLabel(source: string): string {
    return DISPLAY_NAMES[source] || source
}

function formatCurrency(value: number, currency: string = 'USD'): string {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 0 }).format(value)
}

function formatNumber(value: number): string {
    return new Intl.NumberFormat('en-US').format(value)
}

function StatCard({
    label,
    value,
    loading,
    alert,
}: {
    label: string
    value: number
    loading?: boolean
    alert?: boolean
}): JSX.Element {
    return (
        <div className="bg-bg-light rounded-lg border p-3">
            <div className="text-xs text-secondary uppercase tracking-wide">{label}</div>
            {loading ? (
                <LemonSkeleton className="h-7 w-12 mt-1" />
            ) : (
                <div className={`text-2xl font-bold mt-1 tabular-nums ${alert ? 'text-warning' : ''}`}>
                    {value.toLocaleString()}
                </div>
            )}
        </div>
    )
}

function ActionsMenu({ columnName, value }: { columnName: string; value: string }): JSX.Element {
    const [showActions, setShowActions] = useState(false)

    return (
        <Popover
            visible={showActions}
            onClickOutside={() => setShowActions(false)}
            overlay={<NonIntegratedConversionsCellActions columnName={columnName} value={value} />}
        >
            <LemonButton size="xsmall" icon={<IconEllipsis />} onClick={() => setShowActions(!showActions)} />
        </Popover>
    )
}

function CampaignTabContent(): JSX.Element {
    const {
        auditDataLoading,
        filteredCampaigns,
        selectedCampaign,
        selectedUtmCampaign,
        selectedCampaignData,
        sortedUtmCampaigns,
        campaignSearch,
        utmSearch,
        baseCurrency,
    } = useValues(utmAuditLogic)
    const { setSelectedCampaign, setSelectedUtmCampaign, setCampaignSearch, setUtmSearch } = useActions(utmAuditLogic)
    const { openIntegrationSettingsModal } = useActions(marketingAnalyticsSettingsLogic)

    const canMap = selectedCampaign !== null && selectedUtmCampaign !== null && selectedCampaignData !== null

    return (
        <>
            {/* Map campaigns action bar */}
            <div className="flex items-center justify-between p-3 rounded border mb-4">
                <div className="text-sm text-secondary">
                    {canMap
                        ? `Map "${selectedUtmCampaign}" → "${selectedCampaign}"`
                        : 'Select a campaign on the left and a UTM campaign on the right to create a mapping'}
                </div>
                <LemonButton
                    type="primary"
                    size="small"
                    disabled={!canMap}
                    onClick={() => {
                        if (canMap && selectedCampaignData) {
                            const integration = SOURCE_TO_INTEGRATION[selectedCampaignData.source_name.toLowerCase()]
                            if (integration) {
                                openIntegrationSettingsModal(
                                    integration,
                                    'mappings',
                                    selectedUtmCampaign!,
                                    selectedCampaign!
                                )
                            }
                        }
                    }}
                >
                    Map campaign
                </LemonButton>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Left panel: campaigns from ad platforms */}
                <div className="flex flex-col">
                    <div className="flex items-center justify-between mb-2">
                        <h4 className="text-sm font-semibold m-0">Ad platform campaigns</h4>
                        <LemonInput
                            type="search"
                            placeholder="Search..."
                            value={campaignSearch}
                            onChange={setCampaignSearch}
                            size="small"
                            className="max-w-48"
                        />
                    </div>
                    <div className="max-h-[60vh] overflow-y-auto">
                        <LemonTable
                            dataSource={filteredCampaigns}
                            rowKey={(record) => `${record.source_name}-${record.campaign_id}`}
                            onRow={(record) => ({
                                onClick: () => setSelectedCampaign(record.campaign_name),
                                className: 'cursor-pointer',
                            })}
                            rowStatus={(record) => (record.campaign_name === selectedCampaign ? 'highlighted' : null)}
                            columns={[
                                {
                                    title: 'Campaign',
                                    dataIndex: 'campaign_name',
                                    render: (_, record: CampaignAuditResult) => (
                                        <div>
                                            <div className="font-medium">{record.campaign_name}</div>
                                            <div className="text-xs text-secondary">
                                                {record.source_name} · ID: {record.campaign_id} ·{' '}
                                                {formatCurrency(record.spend, baseCurrency)} ·{' '}
                                                {formatNumber(record.clicks)} clicks
                                            </div>
                                        </div>
                                    ),
                                },
                                {
                                    title: 'Status',
                                    width: 120,
                                    render: (_, record: CampaignAuditResult) => {
                                        if (record.issues.length === 0) {
                                            return <LemonTag type="success">OK</LemonTag>
                                        }
                                        const issue = record.issues[0]
                                        return (
                                            <Tooltip title={issue.message}>
                                                <span>
                                                    <LemonTag
                                                        type={issue.severity === 'error' ? 'danger' : 'warning'}
                                                        icon={<IconWarning />}
                                                    >
                                                        {issue.severity === 'error' ? 'Not linked' : 'Source mismatch'}
                                                    </LemonTag>
                                                </span>
                                            </Tooltip>
                                        )
                                    },
                                },
                            ]}
                            size="small"
                            loading={auditDataLoading}
                            emptyState="No campaigns found"
                        />
                    </div>
                </div>

                {/* Right panel: UTM campaign events */}
                <div className="flex flex-col">
                    <div className="flex items-center justify-between mb-2">
                        <h4 className="text-sm font-semibold m-0">UTM campaigns</h4>
                        <LemonInput
                            type="search"
                            placeholder="Search..."
                            value={utmSearch}
                            onChange={setUtmSearch}
                            size="small"
                            className="max-w-48"
                        />
                    </div>
                    <div className="max-h-[60vh] overflow-y-auto">
                        <LemonTable
                            dataSource={sortedUtmCampaigns}
                            rowKey={(record) => `${record.utm_campaign}-${record.utm_source}`}
                            onRow={(record) => ({
                                onClick: () => setSelectedUtmCampaign(record.utm_campaign),
                                className: 'cursor-pointer',
                            })}
                            rowStatus={(record) => (record.utm_campaign === selectedUtmCampaign ? 'highlighted' : null)}
                            columns={[
                                {
                                    title: 'utm_campaign',
                                    dataIndex: 'utm_campaign',
                                    render: (_, record: UtmEvent) => (
                                        <span className="font-mono text-sm">{record.utm_campaign}</span>
                                    ),
                                },
                                {
                                    title: 'utm_source',
                                    dataIndex: 'utm_source',
                                    render: (_, record: UtmEvent) => (
                                        <span className="font-mono text-sm text-secondary">{record.utm_source}</span>
                                    ),
                                },
                                {
                                    title: 'Pageviews',
                                    dataIndex: 'event_count',
                                    width: 80,
                                    render: (_, record: UtmEvent) => formatNumber(record.event_count),
                                },
                                {
                                    title: '',
                                    width: 30,
                                    render: (_, record: UtmEvent) => {
                                        if (record.campaign_match === 'auto') {
                                            return (
                                                <Tooltip title={`Auto-matched to: ${record.matched_campaign}`}>
                                                    <span>
                                                        <IconCheck className="text-success text-lg" />
                                                    </span>
                                                </Tooltip>
                                            )
                                        }
                                        if (record.campaign_match === 'mapped') {
                                            return (
                                                <Tooltip title={`Manually mapped to: ${record.matched_campaign}`}>
                                                    <span>
                                                        <IconLink className="text-primary text-lg" />
                                                    </span>
                                                </Tooltip>
                                            )
                                        }
                                        return null
                                    },
                                },
                                {
                                    title: '',
                                    width: 30,
                                    render: (_, record: UtmEvent) => (
                                        <ActionsMenu columnName="Campaign" value={record.utm_campaign} />
                                    ),
                                },
                            ]}
                            size="small"
                            loading={auditDataLoading}
                            emptyState="No UTM events found"
                        />
                    </div>
                </div>
            </div>
        </>
    )
}

function SourceTabContent(): JSX.Element {
    const { auditDataLoading, aggregatedUtmSources, utmSearch } = useValues(utmAuditLogic)
    const { setUtmSearch } = useActions(utmAuditLogic)

    return (
        <div>
            <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-semibold m-0">UTM sources</h4>
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    value={utmSearch}
                    onChange={setUtmSearch}
                    size="small"
                    className="max-w-48"
                />
            </div>
            <div className="max-h-[70vh] overflow-y-auto">
                <LemonTable
                    dataSource={aggregatedUtmSources}
                    rowKey="utm_source"
                    columns={[
                        {
                            title: 'utm_source',
                            dataIndex: 'utm_source',
                            render: (_, record: AggregatedUtmSource) => (
                                <span className="font-mono text-sm">{record.utm_source}</span>
                            ),
                        },
                        {
                            title: 'Pageviews',
                            dataIndex: 'event_count',
                            width: 100,
                            sorter: (a: AggregatedUtmSource, b: AggregatedUtmSource) => a.event_count - b.event_count,
                            render: (_, record: AggregatedUtmSource) => formatNumber(record.event_count),
                        },
                        {
                            title: 'Integration',
                            width: 150,
                            render: (_, record: AggregatedUtmSource) =>
                                record.integration ? (
                                    <span className="text-sm">{sourceLabel(record.integration)}</span>
                                ) : (
                                    <span className="text-secondary text-sm">—</span>
                                ),
                        },
                        {
                            title: '',
                            width: 30,
                            render: (_, record: AggregatedUtmSource) =>
                                record.mapped ? (
                                    <Tooltip
                                        title={
                                            record.match_type === 'mapped'
                                                ? 'Manually mapped'
                                                : 'Default integration source'
                                        }
                                    >
                                        <span>
                                            {record.match_type === 'mapped' ? (
                                                <IconLink className="text-primary text-lg" />
                                            ) : (
                                                <IconCheck className="text-success text-lg" />
                                            )}
                                        </span>
                                    </Tooltip>
                                ) : null,
                        },
                        {
                            title: '',
                            width: 30,
                            render: (_, record: AggregatedUtmSource) => (
                                <ActionsMenu columnName="Source" value={record.utm_source} />
                            ),
                        },
                    ]}
                    size="small"
                    loading={auditDataLoading}
                    emptyState="No UTM sources found"
                />
            </div>
        </div>
    )
}

function SettingsTabContent({ integrationFilter }: { integrationFilter?: string }): JSX.Element {
    return (
        <div className="space-y-8">
            <section>
                <h4 className="text-sm font-semibold mb-1">Match field</h4>
                <p className="text-secondary text-sm mb-3">
                    Choose whether utm_campaign is matched against campaign names or campaign IDs for each integration.
                </p>
                <CampaignFieldPreferencesConfiguration sourceFilter={integrationFilter} />
            </section>

            <section>
                <h4 className="text-sm font-semibold mb-1">Custom source mappings</h4>
                <p className="text-secondary text-sm mb-3">
                    Map custom utm_source values to an integration when they differ from the defaults.
                </p>
                <CustomSourceMappingsConfiguration sourceFilter={integrationFilter} />
            </section>

            <section>
                <h4 className="text-sm font-semibold mb-1">Campaign name mappings</h4>
                <p className="text-secondary text-sm mb-3">
                    Manually map utm_campaign values to campaigns when names don't match automatically.
                </p>
                <CampaignNameMappingsConfiguration sourceFilter={integrationFilter} />
            </section>
        </div>
    )
}

export function UtmAuditTab(): JSX.Element {
    const {
        auditData,
        auditDataLoading,
        auditDataFailure,
        campaignsWithoutUtmCount,
        activeTab,
        availableSources,
        sourceFilter,
        totalUtmSourcesCount,
        unmappedSourcesCount,
    } = useValues(utmAuditLogic)
    const { setActiveTab, setSourceFilter, loadAuditData } = useActions(utmAuditLogic)
    const { integrationSettingsModal } = useValues(marketingAnalyticsSettingsLogic)
    const { closeIntegrationSettingsModal } = useActions(marketingAnalyticsSettingsLogic)

    const integrationFilter = sourceFilter ? SOURCE_TO_INTEGRATION[sourceFilter] : undefined

    return (
        <div className="mt-4 mb-8 space-y-4">
            {/* Filter bar */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <LemonButton size="small" type="secondary" onClick={() => loadAuditData()}>
                        Reload
                    </LemonButton>
                </div>
                <LemonSelect
                    size="small"
                    value={sourceFilter ?? '__all__'}
                    onChange={(value) => setSourceFilter(value === '__all__' ? null : value)}
                    options={[
                        { value: '__all__', label: 'All integrations' },
                        ...availableSources.map((s) => ({ value: s, label: sourceLabel(s) })),
                    ]}
                />
            </div>

            {/* Explainer */}
            <p className="text-secondary text-sm">
                PostHog uses UTM parameters (utm_source, utm_campaign) from your pageview events to connect website
                traffic back to your ad platform campaigns. This connection powers{' '}
                <Tooltip title="Conversion goals are events or actions you define in settings (e.g. purchase, sign up) that are tracked and attributed to your marketing campaigns.">
                    <span className="underline decoration-dotted cursor-help">marketing conversion goal</span>
                </Tooltip>{' '}
                attribution. If campaigns aren't linked to UTM events, their conversion goals won't be tracked. The best
                fix is to update your UTM parameters directly in your ad platform campaigns. If that's not possible, you
                can create a manual mapping here to bridge the gap.
            </p>

            {/* Summary */}
            {auditDataFailure ? (
                <LemonBanner type="error">
                    Failed to load integration health data. This may be because the feature is not yet enabled for your
                    account.
                </LemonBanner>
            ) : (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <StatCard label="Campaigns" value={auditData?.total_campaigns ?? 0} loading={auditDataLoading} />
                    <StatCard
                        label="Not linked"
                        value={campaignsWithoutUtmCount}
                        loading={auditDataLoading}
                        alert={campaignsWithoutUtmCount > 0}
                    />
                    <StatCard label="UTM sources" value={totalUtmSourcesCount} loading={auditDataLoading} />
                    <StatCard
                        label="Unmapped sources"
                        value={unmappedSourcesCount}
                        loading={auditDataLoading}
                        alert={unmappedSourcesCount > 0}
                    />
                </div>
            )}

            {/* Tabs */}
            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as HealthTab)}
                tabs={[
                    {
                        key: 'campaign',
                        label: 'Campaigns',
                        content: <CampaignTabContent />,
                    },
                    {
                        key: 'source',
                        label: 'Sources',
                        content: <SourceTabContent />,
                    },
                    {
                        key: 'settings',
                        label: 'UTM preferences',
                        content: <SettingsTabContent integrationFilter={integrationFilter} />,
                    },
                ]}
            />

            {integrationSettingsModal.integration && (
                <IntegrationSettingsModal
                    integrationName={integrationSettingsModal.integration}
                    isOpen={integrationSettingsModal.isOpen}
                    onClose={closeIntegrationSettingsModal}
                    initialTab={integrationSettingsModal.initialTab}
                    initialUtmValue={integrationSettingsModal.initialUtmValue}
                    initialCampaignName={integrationSettingsModal.initialCampaignName}
                />
            )}
        </div>
    )
}
