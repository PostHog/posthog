import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowRight, IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonCard, Link } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import {
    VALID_NON_NATIVE_MARKETING_SOURCES,
    VALID_SELF_MANAGED_MARKETING_SOURCES,
    getEnabledNativeMarketingSources,
} from '../../web-analytics/tabs/marketing-analytics/frontend/logic/utils'

interface MarketingSource {
    id: string
    isConnected: boolean
    category: 'native' | 'external' | 'self-managed'
}

interface AddSourceStepProps {
    onContinue: () => void
    hasSources: boolean
}

export function AddSourceStep({ onContinue, hasSources }: AddSourceStepProps): JSX.Element {
    const { validExternalTables, validNativeSources } = useValues(marketingAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { reportMarketingAnalyticsDataSourceConnected } = useActions(eventUsageLogic)
    const { addProductIntent } = useActions(teamLogic)

    const enabledNativeSources = getEnabledNativeMarketingSources(featureFlags)

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
        router.actions.push(urls.dataWarehouseSourceNew(sourceId))
    }

    const nativeSources = allSources.filter((s) => s.category === 'native')
    const externalSources = allSources.filter((s) => s.category === 'external')
    const selfManagedSources = allSources.filter((s) => s.category === 'self-managed')

    const totalConnected = validNativeSources.length + validExternalTables.length

    return (
        <LemonCard hoverEffect={false}>
            <div className="space-y-3">
                {/* Header */}
                <div className="flex items-center justify-between">
                    <div>
                        <h3 className="text-base font-semibold mb-0.5">Connect your marketing sources</h3>
                        <p className="text-xs text-muted-alt">
                            {hasSources
                                ? `${totalConnected} source${totalConnected !== 1 ? 's' : ''} connected — click to add more`
                                : 'Select a platform to connect (opens data warehouse setup)'}
                        </p>
                    </div>
                </div>

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
                        <div className="text-xs font-medium text-muted mb-1.5">Data warehouse</div>
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
                        <div className="text-xs font-medium text-muted mb-1.5">Self-managed</div>
                        <div className="flex flex-wrap gap-2">
                            {selfManagedSources.map((source) => (
                                <SourceChip key={source.id} source={source} onSelect={handleSourceSelect} />
                            ))}
                        </div>
                    </div>
                )}

                {/* Footer */}
                <div className="flex items-center justify-between pt-3 border-t border-primary">
                    <Link
                        to="https://posthog.com/docs/web-analytics/marketing-analytics"
                        target="_blank"
                        className="text-xs"
                    >
                        View docs
                    </Link>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={onContinue}
                        sideIcon={<IconArrowRight />}
                        disabledReason={!hasSources ? 'Connect at least one source' : undefined}
                    >
                        Continue
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}

function SourceChip({ source, onSelect }: { source: MarketingSource; onSelect: (id: string) => void }): JSX.Element {
    return (
        <button
            type="button"
            className={cn(
                'flex items-center gap-2 px-2.5 py-1.5 rounded-md border transition-all',
                source.isConnected
                    ? 'border-success bg-success-lightest'
                    : 'border-primary bg-bg-light hover:border-primary-dark hover:bg-fill-button-tertiary-hover',
                'cursor-pointer'
            )}
            onClick={() => onSelect(source.id)}
        >
            <DataWarehouseSourceIcon type={source.id} size="xsmall" disableTooltip />
            <span className="text-sm font-medium">{source.id}</span>
            {source.isConnected && <IconCheckCircle className="w-3.5 h-3.5 text-success" />}
        </button>
    )
}
