import { useActions, useValues } from 'kea'

import * as moneyPng from '@posthog/brand/hoggies/png/money'
import { IconArrowRight, IconCheckCircle, IconExternal, IconInfo } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, Link, Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { marketingAnalyticsLogic } from '../../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import {
    VALID_NON_NATIVE_MARKETING_SOURCES,
    VALID_SELF_MANAGED_MARKETING_SOURCES,
    getEnabledNativeMarketingSourcesInDisplayOrder,
    nativeSourceDisplayLabel,
} from '../../web-analytics/tabs/marketing-analytics/frontend/logic/utils'
import { marketingOnboardingLogic } from './marketingOnboardingLogic'

const HedgehogMoney = pngHoggie(moneyPng)

interface MarketingSource {
    id: string
    isConnected: boolean
    category: 'native' | 'external' | 'self-managed'
}

interface AddSourceStepProps {
    onContinue?: () => void
    hasSources: boolean
    onBack?: () => void
}

export function AddSourceStep({ onContinue, hasSources, onBack }: AddSourceStepProps): JSX.Element {
    const { manualSourceSearch } = useValues(marketingOnboardingLogic)
    const { setManualSourceSearch } = useActions(marketingOnboardingLogic)
    const { validExternalTables, validNativeSources } = useValues(marketingAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { reportMarketingAnalyticsDataSourceConnected } = useActions(eventUsageLogic)
    const { addProductIntent } = useActions(teamLogic)

    const enabledNativeSources = getEnabledNativeMarketingSourcesInDisplayOrder(featureFlags)

    const allSources: MarketingSource[] = [
        ...enabledNativeSources.map((sourceType) => ({
            id: sourceType,
            isConnected: validNativeSources.some((source) => source.source.source_type === sourceType),
            category: 'native' as const,
        })),
        ...VALID_NON_NATIVE_MARKETING_SOURCES.map((sourceType) => ({
            id: sourceType,
            isConnected: validExternalTables.some((table) => table.source_type === sourceType),
            category: 'external' as const,
        })),
        ...VALID_SELF_MANAGED_MARKETING_SOURCES.map((sourceType) => ({
            id: sourceType,
            isConnected: validExternalTables.some((table) => table.source_type === sourceType),
            category: 'self-managed' as const,
        })),
    ]

    const handleSourceSelect = (sourceId: string): void => {
        reportMarketingAnalyticsDataSourceConnected(sourceId)
        addProductIntent({
            product_type: ProductKey.MARKETING_ANALYTICS,
            intent_context: ProductIntentContext.MARKETING_ANALYTICS_DATA_SOURCE_CONNECTED,
            metadata: { source_type: sourceId },
        })
        window.open(
            urls.dataWarehouseSourceNew(sourceId, urls.marketingAnalyticsApp(), 'Marketing analytics'),
            '_blank',
            'noopener'
        )
    }

    const nativeSources = allSources.filter(
        (s) =>
            nativeSourceDisplayLabel(s.id).toLowerCase().includes(manualSourceSearch.toLowerCase()) &&
            s.category === 'native'
    )
    const externalSources = allSources.filter(
        (s) =>
            nativeSourceDisplayLabel(s.id).toLowerCase().includes(manualSourceSearch.toLowerCase()) &&
            s.category === 'external'
    )
    const selfManagedSources = allSources.filter(
        (s) =>
            nativeSourceDisplayLabel(s.id).toLowerCase().includes(manualSourceSearch.toLowerCase()) &&
            s.category === 'self-managed'
    )

    const totalConnected = validNativeSources.length + validExternalTables.length

    return (
        <LemonCard hoverEffect={false} className="max-w-3xl w-full mx-auto mt-6 !p-0 overflow-hidden">
            <div className="p-6 space-y-3">
                {/* Header */}
                <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                        <h3 className="text-base font-semibold mb-0.5">Connect your marketing sources</h3>
                        <p className="text-xs text-muted-alt">
                            {hasSources
                                ? `${totalConnected} source${totalConnected !== 1 ? 's' : ''} connected. Choose another platform to connect.`
                                : 'Choose a platform to start importing spend data.'}
                        </p>
                    </div>
                    <HedgehogMoney className="w-20 shrink-0" />
                </div>

                <LemonInput
                    type="search"
                    placeholder="Search integrations"
                    value={manualSourceSearch}
                    onChange={setManualSourceSearch}
                />
                {!nativeSources.length && !externalSources.length && !selfManagedSources.length && (
                    <p className="text-secondary">No integrations match your search.</p>
                )}
                {/* Native Sources */}
                {nativeSources.length > 0 && (
                    <div>
                        <div className="text-xs font-medium text-muted mb-1.5">Native integrations (recommended)</div>
                        <div className="flex flex-wrap gap-2">
                            {nativeSources.map((source) => (
                                <SourceChip key={source.id} source={source} onSelect={handleSourceSelect} />
                            ))}
                        </div>
                    </div>
                )}

                {/* External Sources */}
                {externalSources.length > 0 && (
                    <div>
                        <div className="text-xs font-medium text-muted mb-1.5 flex items-center gap-1">
                            Data warehouse
                            <Tooltip
                                title="Import marketing data you already have in a data warehouse like BigQuery."
                                delayMs={0}
                            >
                                <IconInfo className="w-3 h-3 cursor-help" />
                            </Tooltip>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            {externalSources.map((source) => (
                                <SourceChip key={source.id} source={source} onSelect={handleSourceSelect} />
                            ))}
                        </div>
                    </div>
                )}

                {/* Self-managed Sources */}
                {selfManagedSources.length > 0 && (
                    <div>
                        <div className="text-xs font-medium text-muted mb-1.5 flex items-center gap-1">
                            Self-managed
                            <Tooltip
                                title="Connect your own data source (e.g. S3, GCS) where you already store marketing data."
                                delayMs={0}
                            >
                                <IconInfo className="w-3 h-3 cursor-help" />
                            </Tooltip>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            {selfManagedSources.map((source) => (
                                <SourceChip key={source.id} source={source} onSelect={handleSourceSelect} />
                            ))}
                        </div>
                    </div>
                )}
            </div>
            <div className="border-t p-4 flex flex-wrap items-center justify-between gap-3 bg-bg-light">
                {onBack && (
                    <LemonButton type="secondary" size="small" onClick={onBack}>
                        Back to suggestions
                    </LemonButton>
                )}
                <Link
                    to="https://posthog.com/docs/web-analytics/marketing-analytics"
                    target="_blank"
                    className="text-xs"
                >
                    View docs
                </Link>
                {onContinue && (
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={onContinue}
                        sideIcon={<IconArrowRight />}
                        data-attr="marketing-onboarding-continue"
                    >
                        {hasSources ? 'Continue to dashboard' : 'Skip for now'}
                    </LemonButton>
                )}
            </div>
        </LemonCard>
    )
}

function SourceChip({ source, onSelect }: { source: MarketingSource; onSelect: (id: string) => void }): JSX.Element {
    return (
        <LemonButton
            type="secondary"
            icon={<SourceIcon type={source.id} size="small" disableTooltip />}
            sideIcon={<IconExternal className="!w-3 !h-3 text-muted" />}
            onClick={() => onSelect(source.id)}
            data-attr="marketing-manual-connect-source"
        >
            {nativeSourceDisplayLabel(source.id)}
            {source.isConnected && <IconCheckCircle className="ml-2 text-success" />}
        </LemonButton>
    )
}
