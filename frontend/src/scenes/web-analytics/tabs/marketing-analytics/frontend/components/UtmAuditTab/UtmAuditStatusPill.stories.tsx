import { Meta } from '@storybook/react'

import { IconWarning } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { CampaignAuditResult } from '../../logic/utmAuditLogic'
import { issueLabel, issueTooltip } from './UtmAuditTab'

const meta: Meta = {
    title: 'Scenes-App/Web Analytics/UTM Audit Status Pill',
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

const baseCampaign: CampaignAuditResult = {
    campaign_name: 'Campaign',
    campaign_id: '1',
    source_name: 'google',
    spend: 500,
    clicks: 100,
    impressions: 5000,
    has_utm_events: false,
    event_count: 0,
    issues: [],
}

function StatusPill({ record }: { record: CampaignAuditResult }): JSX.Element {
    const issue = record.issues[0]
    return (
        <div className="p-8 flex flex-col gap-24">
            <div className="text-xs text-secondary">
                {record.source_name} · {record.campaign_name}
            </div>
            <Tooltip visible placement="bottom-start" title={issueTooltip(record)}>
                <span>
                    <LemonTag type={issue.severity === 'error' ? 'danger' : 'warning'} icon={<IconWarning />}>
                        {issueLabel(record)}
                    </LemonTag>
                </span>
            </Tooltip>
        </div>
    )
}

export function NotLinked(): JSX.Element {
    return (
        <StatusPill
            record={{
                ...baseCampaign,
                campaign_name: 'Summer Promo',
                issues: [
                    {
                        field: 'utm_campaign',
                        severity: 'error',
                        kind: 'not_linked',
                        message: '',
                        alternative_sources: [],
                        shared_with_integrations: [],
                    },
                ],
            }}
        />
    )
}

export function MissingSource(): JSX.Element {
    return (
        <StatusPill
            record={{
                ...baseCampaign,
                campaign_name: 'Performance Max - Generic',
                issues: [
                    {
                        field: 'utm_source',
                        severity: 'warning',
                        kind: 'missing_source',
                        message: '',
                        alternative_sources: [],
                        shared_with_integrations: [],
                    },
                ],
            }}
        />
    )
}

export function SourceMismatch(): JSX.Element {
    return (
        <StatusPill
            record={{
                ...baseCampaign,
                campaign_name: 'Brand Q3',
                issues: [
                    {
                        field: 'utm_source',
                        severity: 'warning',
                        kind: 'no_tagged_events',
                        message: '',
                        alternative_sources: [
                            { utm_source: 'facebook', event_count: 120 },
                            { utm_source: 'meta', event_count: 30 },
                        ],
                        shared_with_integrations: [],
                    },
                ],
            }}
        />
    )
}

export function NameCollision(): JSX.Element {
    return (
        <StatusPill
            record={{
                ...baseCampaign,
                source_name: 'bing',
                campaign_name: 'Survey',
                issues: [
                    {
                        field: 'utm_campaign',
                        severity: 'warning',
                        kind: 'name_collision',
                        message: '',
                        alternative_sources: [],
                        shared_with_integrations: ['google'],
                    },
                ],
            }}
        />
    )
}
