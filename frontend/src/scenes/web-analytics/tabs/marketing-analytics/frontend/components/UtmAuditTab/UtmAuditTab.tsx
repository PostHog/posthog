import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconEllipsis, IconWarning } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonSegmentedButton,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTabs,
    LemonTag,
    Popover,
    Tooltip,
} from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { IconLink } from 'lib/lemon-ui/icons'

import { type CampaignFieldPreference, MatchField, NativeMarketingSource } from '~/queries/schema/schema-general'

import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import type {
    AggregatedUtmSource,
    CampaignAuditResult,
    HealthTab,
    MappingPair,
    UtmEvent,
    UtmIssue,
    UtmIssueKind,
} from '../../logic/utmAuditLogic'
import { SOURCE_TO_INTEGRATION, utmAuditLogic } from '../../logic/utmAuditLogic'
import { NonIntegratedConversionsCellActions } from '../NonIntegratedConversionsTable/NonIntegratedConversionsCellActions'
import { CampaignFieldPreferencesConfiguration } from '../settings/CampaignFieldPreferencesConfiguration'
import { CampaignNameMappingsConfiguration } from '../settings/CampaignNameMappingsConfiguration'
import { CustomSourceMappingsConfiguration } from '../settings/CustomSourceMappingsConfiguration'
import { IntegrationSettingsModal } from '../settings/IntegrationSettingsModal'

const ISSUE_LABELS: Record<UtmIssueKind, string> = {
    not_linked: 'Not linked',
    name_collision: 'Name collision',
    no_tagged_events: 'Source mismatch',
    unknown_source: 'Source mismatch',
}

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

/** Editing the audit's config is admin-only, same as the settings screens these controls write to. */
function useConfigRestriction(): string | null {
    return useRestrictedArea({ scope: RestrictionScope.Project, minimumAccessLevel: TeamMembershipLevel.Admin })
}

/** The name-vs-ID toggle, surfaced wherever the audit wants to recommend it. */
function MatchFieldToggle({ integration }: { integration: NativeMarketingSource }): JSX.Element {
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCampaignFieldPreferences } = useActions(marketingAnalyticsSettingsLogic)
    const restrictedReason = useConfigRestriction()

    const preferences = marketingAnalyticsConfig?.campaign_field_preferences || {}
    const value = preferences[integration]?.match_field || MatchField.CAMPAIGN_NAME

    return (
        <LemonSegmentedButton
            size="xsmall"
            value={value}
            onChange={(matchField) =>
                updateCampaignFieldPreferences({
                    ...preferences,
                    [integration]: { match_field: matchField as CampaignFieldPreference['match_field'] },
                })
            }
            options={[
                { value: MatchField.CAMPAIGN_NAME, label: 'Campaign name' },
                { value: MatchField.CAMPAIGN_ID, label: 'Campaign ID' },
            ]}
            disabledReason={restrictedReason ?? undefined}
        />
    )
}

/** Expands one audit issue into the remediations the backend computed for it. */
function IssueDetail({ campaign, issue }: { campaign: CampaignAuditResult; issue: UtmIssue }): JSX.Element {
    const { allMappedSources } = useValues(utmAuditLogic)
    const { marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { updateCustomSourceMappings, openIntegrationSettingsModal } = useActions(marketingAnalyticsSettingsLogic)
    const restrictedReason = useConfigRestriction()

    const integration = SOURCE_TO_INTEGRATION[campaign.source_name.toLowerCase()]
    const alternativeSources = issue.alternative_sources ?? []
    const sharedWith = issue.shared_with_integrations ?? []
    const suggestedActions = issue.suggested_actions ?? []
    // Only offer to claim sources no other integration already owns — mapping one of those
    // would silently move that integration's traffic over here.
    const claimableSources = alternativeSources.filter((s) => !allMappedSources.has(s.utm_source))

    const addSourceMapping = (utmSource: string): void => {
        if (!integration) {
            return
        }
        const existing = marketingAnalyticsConfig?.custom_source_mappings || {}
        updateCustomSourceMappings({
            ...existing,
            [integration]: [...new Set([...(existing[integration] || []), utmSource])],
        })
    }

    return (
        <div className="p-3 max-w-md space-y-3">
            <div className="font-semibold text-sm">{issue.message}</div>

            {alternativeSources.length > 0 && (
                <div>
                    <div className="text-xs text-secondary uppercase tracking-wide mb-1">Events are tagged with</div>
                    <div className="space-y-1">
                        {alternativeSources.map((source) => (
                            <div key={source.utm_source} className="flex items-center justify-between gap-2 text-sm">
                                <span className="font-mono">utm_source={source.utm_source}</span>
                                <span className="text-secondary tabular-nums">
                                    {formatNumber(source.event_count)} pageviews
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {sharedWith.length > 0 && (
                <div className="text-sm">
                    The same campaign name is already matching events on{' '}
                    {sharedWith.map((s) => sourceLabel(s)).join(', ')}.
                </div>
            )}

            <div>
                <div className="text-xs text-secondary uppercase tracking-wide mb-1">How to fix</div>
                <div className="space-y-2">
                    {suggestedActions.includes('fix_platform_urls') && (
                        <div className="text-sm">
                            Tag this campaign's URLs with{' '}
                            <span className="font-mono text-xs">utm_source={campaign.source_name}</span> and{' '}
                            <span className="font-mono text-xs">utm_campaign={campaign.campaign_name}</span>. This is
                            the only fix that also works for anything else reading your UTMs.
                        </div>
                    )}

                    {suggestedActions.includes('add_source_mapping') &&
                        claimableSources.map((source) => (
                            <LemonButton
                                key={source.utm_source}
                                type="secondary"
                                size="small"
                                fullWidth
                                disabledReason={
                                    restrictedReason ??
                                    (integration ? undefined : 'This source has no matching integration')
                                }
                                onClick={() => addSourceMapping(source.utm_source)}
                            >
                                Count "{source.utm_source}" as {sourceLabel(campaign.source_name)}
                            </LemonButton>
                        ))}

                    {suggestedActions.includes('switch_to_id_match') && integration && (
                        <div>
                            <div className="text-sm mb-1">
                                Matching on campaign ID tells the platforms apart, as long as your URLs use the ID in{' '}
                                <span className="font-mono text-xs">utm_campaign</span>.
                            </div>
                            <MatchFieldToggle integration={integration} />
                        </div>
                    )}

                    {integration && (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            fullWidth
                            onClick={() =>
                                openIntegrationSettingsModal(integration, 'mappings', '', campaign.campaign_name)
                            }
                        >
                            Map a utm_campaign value to this campaign
                        </LemonButton>
                    )}
                </div>
            </div>
        </div>
    )
}

function IssueCell({ campaign }: { campaign: CampaignAuditResult }): JSX.Element {
    const [showDetail, setShowDetail] = useState(false)

    if (campaign.issues.length === 0) {
        return <LemonTag type="success">OK</LemonTag>
    }

    const issue = campaign.issues[0]
    const label = ISSUE_LABELS[issue.kind] ?? (issue.severity === 'error' ? 'Not linked' : 'Source mismatch')

    return (
        <Popover
            visible={showDetail}
            onClickOutside={() => setShowDetail(false)}
            overlay={<IssueDetail campaign={campaign} issue={issue} />}
        >
            <span
                onClick={(e) => {
                    e.stopPropagation()
                    setShowDetail(!showDetail)
                }}
            >
                <LemonTag
                    type={issue.severity === 'error' ? 'danger' : 'warning'}
                    icon={<IconWarning />}
                    className="cursor-pointer"
                >
                    {label}
                </LemonTag>
            </span>
        </Popover>
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

/** Preview of what a bulk map is about to write, so nothing is applied sight-unseen. */
function MappingPreview({ pairs }: { pairs: MappingPair[] }): JSX.Element {
    return (
        <div className="p-3 max-w-lg space-y-1">
            {pairs.map((pair) => (
                <div key={`${pair.integration}-${pair.matchValue}-${pair.utmCampaign}`} className="text-sm">
                    <span className="font-mono">{pair.utmCampaign}</span>
                    <span className="text-secondary"> → </span>
                    <span className="font-medium">{pair.campaignName}</span>
                    {pair.reason === 'case_only' && (
                        <span className="text-secondary text-xs"> (capitalization only)</span>
                    )}
                </div>
            ))}
        </div>
    )
}

function SuggestionsBanner(): JSX.Element | null {
    const { autoMappingSuggestions } = useValues(utmAuditLogic)
    const { applyMappings } = useActions(utmAuditLogic)
    const restrictedReason = useConfigRestriction()
    const [showPreview, setShowPreview] = useState(false)

    if (autoMappingSuggestions.length === 0) {
        return null
    }

    const caseOnlyCount = autoMappingSuggestions.filter((p) => p.reason === 'case_only').length

    return (
        <LemonBanner type="info" className="mb-4">
            <div className="flex items-center justify-between gap-3 flex-wrap">
                <span>
                    {autoMappingSuggestions.length} utm_campaign{' '}
                    {autoMappingSuggestions.length === 1 ? 'value looks' : 'values look'} like a campaign we already
                    know about
                    {caseOnlyCount > 0
                        ? `, ${caseOnlyCount} of them differing only by capitalization. Attribution matches these values exactly, so a mapping is what makes them count.`
                        : '. Mapping them lets their conversions attribute to the campaign.'}
                </span>
                <div className="flex items-center gap-2">
                    <Popover
                        visible={showPreview}
                        onClickOutside={() => setShowPreview(false)}
                        overlay={<MappingPreview pairs={autoMappingSuggestions} />}
                    >
                        <LemonButton type="secondary" size="small" onClick={() => setShowPreview(!showPreview)}>
                            Review
                        </LemonButton>
                    </Popover>
                    <LemonButton
                        type="primary"
                        size="small"
                        disabledReason={restrictedReason ?? undefined}
                        onClick={() => applyMappings(autoMappingSuggestions)}
                    >
                        Map all {autoMappingSuggestions.length}
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}

function CampaignTabContent(): JSX.Element {
    const {
        auditDataLoading,
        filteredCampaigns,
        selectedCampaigns,
        selectedUtmCampaigns,
        pendingMappings,
        sortedUtmCampaigns,
        campaignSearch,
        utmSearch,
        baseCurrency,
    } = useValues(utmAuditLogic)
    const {
        toggleCampaign,
        toggleUtmCampaign,
        setSelectedCampaigns,
        setSelectedUtmCampaigns,
        clearMappingSelection,
        applyMappings,
        setCampaignSearch,
        setUtmSearch,
    } = useActions(utmAuditLogic)
    const restrictedReason = useConfigRestriction()
    const [showPendingPreview, setShowPendingPreview] = useState(false)

    const selectedCampaignsSet = new Set(selectedCampaigns)
    const selectedUtmSet = new Set(selectedUtmCampaigns)
    const skippedCount = selectedUtmCampaigns.length - pendingMappings.length

    let mappingSummary: string
    if (selectedCampaigns.length === 0 && selectedUtmCampaigns.length === 0) {
        mappingSummary = 'Pick campaigns on the left and utm_campaign values on the right to map them in one go'
    } else if (pendingMappings.length === 0) {
        mappingSummary =
            selectedCampaigns.length === 0
                ? 'Also pick at least one ad platform campaign'
                : 'Also pick at least one utm_campaign value'
    } else {
        mappingSummary = `Map ${pendingMappings.length} ${pendingMappings.length === 1 ? 'value' : 'values'}`
        if (skippedCount > 0) {
            mappingSummary += ` · ${skippedCount} skipped as too different or already mapped`
        }
    }

    return (
        <>
            <SuggestionsBanner />

            {/* Map campaigns action bar */}
            <div className="flex items-center justify-between gap-3 p-3 rounded border mb-4 flex-wrap">
                <div className="text-sm text-secondary">{mappingSummary}</div>
                <div className="flex items-center gap-2">
                    {(selectedCampaigns.length > 0 || selectedUtmCampaigns.length > 0) && (
                        <LemonButton type="tertiary" size="small" onClick={clearMappingSelection}>
                            Clear
                        </LemonButton>
                    )}
                    {pendingMappings.length > 1 && (
                        <Popover
                            visible={showPendingPreview}
                            onClickOutside={() => setShowPendingPreview(false)}
                            overlay={<MappingPreview pairs={pendingMappings} />}
                        >
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => setShowPendingPreview(!showPendingPreview)}
                            >
                                Review
                            </LemonButton>
                        </Popover>
                    )}
                    <LemonButton
                        type="primary"
                        size="small"
                        disabledReason={
                            restrictedReason ?? (pendingMappings.length === 0 ? 'Nothing selected to map' : undefined)
                        }
                        onClick={() => applyMappings(pendingMappings)}
                    >
                        {pendingMappings.length > 1 ? `Map ${pendingMappings.length} campaigns` : 'Map campaign'}
                    </LemonButton>
                </div>
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
                                onClick: () => toggleCampaign(record.campaign_name),
                                className: 'cursor-pointer',
                            })}
                            rowStatus={(record) =>
                                selectedCampaignsSet.has(record.campaign_name) ? 'highlighted' : null
                            }
                            columns={[
                                {
                                    title: (
                                        <LemonCheckbox
                                            checked={
                                                filteredCampaigns.length > 0 &&
                                                filteredCampaigns.every((c) =>
                                                    selectedCampaignsSet.has(c.campaign_name)
                                                )
                                            }
                                            onChange={(checked) =>
                                                setSelectedCampaigns(
                                                    checked ? filteredCampaigns.map((c) => c.campaign_name) : []
                                                )
                                            }
                                            aria-label="Select all campaigns shown"
                                        />
                                    ),
                                    width: 0,
                                    render: (_, record: CampaignAuditResult) => (
                                        <div onClick={(e) => e.stopPropagation()}>
                                            <LemonCheckbox
                                                checked={selectedCampaignsSet.has(record.campaign_name)}
                                                onChange={() => toggleCampaign(record.campaign_name)}
                                                aria-label={`Select ${record.campaign_name}`}
                                            />
                                        </div>
                                    ),
                                },
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
                                    render: (_, record: CampaignAuditResult) => <IssueCell campaign={record} />,
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
                                onClick: () => toggleUtmCampaign(record.utm_campaign),
                                className: 'cursor-pointer',
                            })}
                            rowStatus={(record) => (selectedUtmSet.has(record.utm_campaign) ? 'highlighted' : null)}
                            columns={[
                                {
                                    title: (
                                        <LemonCheckbox
                                            checked={
                                                sortedUtmCampaigns.length > 0 &&
                                                sortedUtmCampaigns.every((e) => selectedUtmSet.has(e.utm_campaign))
                                            }
                                            onChange={(checked) =>
                                                setSelectedUtmCampaigns(
                                                    checked ? sortedUtmCampaigns.map((e) => e.utm_campaign) : []
                                                )
                                            }
                                            aria-label="Select all utm_campaign values shown"
                                        />
                                    ),
                                    width: 0,
                                    render: (_, record: UtmEvent) => (
                                        <div onClick={(e) => e.stopPropagation()}>
                                            <LemonCheckbox
                                                checked={selectedUtmSet.has(record.utm_campaign)}
                                                onChange={() => toggleUtmCampaign(record.utm_campaign)}
                                                aria-label={`Select ${record.utm_campaign}`}
                                            />
                                        </div>
                                    ),
                                },
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
            <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                    <LemonButton size="small" type="secondary" onClick={() => loadAuditData()}>
                        Reload
                    </LemonButton>
                    {/* The fix the audit most often recommends, so it lives here rather than only in settings. */}
                    {integrationFilter && (
                        <div className="flex items-center gap-2">
                            <span className="text-sm text-secondary">Match utm_campaign by</span>
                            <MatchFieldToggle integration={integrationFilter} />
                        </div>
                    )}
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
