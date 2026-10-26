import { useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import type { KnowledgeUsageMeter } from '../../api'
import { businessKnowledgeUsageLogic } from './businessKnowledgeUsageLogic'

function MeterRow({ label, unit, meter }: { label: string; unit: string; meter: KnowledgeUsageMeter }): JSX.Element {
    // The allowance and the billing limit are organization-wide, so compare them with the organization's usage
    // once billing has synced it. Before the first sync, show this project's usage against the free allowance.
    const synced = meter.organization_used !== null
    const used = meter.organization_used ?? meter.used
    // Synced with no limit means a paid plan with no billing limit: there is no ceiling to fill.
    const ceiling = synced ? meter.billing_limit : meter.free_allowance
    const percent = ceiling ? (used / ceiling) * 100 : 0
    return (
        <div className="flex flex-col gap-1 min-w-60 flex-1">
            <div className="flex justify-between text-sm">
                <span className="font-semibold">{label}</span>
                <span className="text-secondary">
                    {ceiling !== null
                        ? `${humanFriendlyNumber(used)} / ${humanFriendlyNumber(ceiling)} ${unit}`
                        : `${humanFriendlyNumber(used)} ${unit}, no billing limit`}
                </span>
            </div>
            {ceiling !== null && (
                <LemonProgress
                    percent={percent}
                    strokeColor={meter.limited ? 'var(--danger)' : percent >= 80 ? 'var(--warning)' : undefined}
                />
            )}
            <span className="text-xs text-secondary">
                {humanFriendlyNumber(meter.free_allowance)} {unit} free each month, then billed per use. This project
                used {humanFriendlyNumber(meter.used)}.
            </span>
        </div>
    )
}

export function BusinessKnowledgeUsageMeter(): JSX.Element | null {
    const { usage, ingestionLimited, retrievalLimited } = useValues(businessKnowledgeUsageLogic)

    if (!usage) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            {(ingestionLimited || retrievalLimited) && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Raise billing limit',
                        to: urls.organizationBilling([ProductKey.BUSINESS_KNOWLEDGE]),
                    }}
                >
                    {ingestionLimited && retrievalLimited
                        ? 'Your organization reached its business knowledge limits. Sources can’t be added or refreshed, and searches are paused. Support replies and PostHog AI keep working without your knowledge base.'
                        : ingestionLimited
                          ? 'Your organization reached its business knowledge ingestion limit. Sources can’t be added or refreshed, but existing knowledge is still searchable.'
                          : 'Your organization reached its business knowledge query limit. Searches are paused. Support replies and PostHog AI keep working without your knowledge base.'}
                </LemonBanner>
            )}
            <div className="flex flex-wrap gap-6 items-start">
                <MeterRow label="Chunks ingested" unit="chunks" meter={usage.chunks} />
                <MeterRow label="Queries" unit="queries" meter={usage.queries} />
                <LemonButton
                    type="secondary"
                    size="small"
                    to={urls.organizationBilling([ProductKey.BUSINESS_KNOWLEDGE])}
                >
                    Billing
                </LemonButton>
            </div>
        </div>
    )
}
