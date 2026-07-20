import { BindLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowLeft, IconCheckCircle, IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { NewSourcesWizard } from 'products/data_warehouse/frontend/scenes/NewSourceScene/NewSourceScene'
import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

/**
 * "Connect your data" body for the context-first onboarding flow. Lets the user connect an external
 * data source (Stripe, Postgres, Hubspot, …) inline (picker plus the real source wizard) so business
 * context (revenue, usage, support) lands in PostHog for agents to reason over. No full-page redirect.
 *
 * Body content only: the parent shell owns the title, progress, and Back/Skip/Continue navigation.
 * Reuses availableSourcesLogic (the source catalog) and sourceWizardLogic (connect flow + the
 * already-connected join). This component mounts no new logic of its own.
 */
export function ContextWarehouseStep(): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)

    if (availableSourcesLoading) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-4 w-2/3" />
                <LemonSkeleton className="h-12" repeat={3} />
            </div>
        )
    }

    // availableSourcesLogic returns null on a 403 (no warehouse access) and leaves it null on any
    // load error. Once loading has finished, null means "couldn't load" — show that, not a skeleton
    // forever. The step is skippable, so the user can still move on.
    if (availableSources === null) {
        return (
            <p className="text-sm text-muted m-0">
                Couldn't load data sources right now. You can connect one later from settings, or skip for now to keep
                going.
            </p>
        )
    }

    return (
        <BindLogic logic={sourceWizardLogic} props={{ availableSources }}>
            <ContextWarehouseStepInner />
        </BindLogic>
    )
}

function ContextWarehouseStepInner(): JSX.Element {
    const { connectors } = useValues(sourceWizardLogic)
    // null = picker, otherwise show the inline wizard pre-selected to this source.
    const [connectingTo, setConnectingTo] = useState<ExternalDataSourceType | null>(null)
    const [showAll, setShowAll] = useState(false)
    const [search, setSearch] = useState('')

    const releasedConnectors = connectors.filter((c: SourceConfig) => !c.unreleasedSource)
    const connectedConnectors = releasedConnectors.filter((c: SourceConfig) => c.existingSource)
    const connectableConnectors = releasedConnectors.filter((c: SourceConfig) => !c.existingSource)

    const featuredConnectors = connectableConnectors.filter((c: SourceConfig) => c.featured)
    const hiddenConnectors = connectableConnectors.filter((c: SourceConfig) => !c.featured)
    // A search shows every matching source; with no search, lead with featured + a "show more" toggle.
    const searchTerm = search.trim().toLowerCase()
    const pickerConnectors = searchTerm
        ? connectableConnectors.filter((c: SourceConfig) => (c.label ?? c.name).toLowerCase().includes(searchTerm))
        : showAll
          ? connectableConnectors
          : featuredConnectors

    if (connectingTo) {
        return (
            <div className="flex flex-col gap-3">
                <div>
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<IconArrowLeft />}
                        onClick={() => setConnectingTo(null)}
                    >
                        Back to sources
                    </LemonButton>
                </div>
                <LemonCard hoverEffect={false} className="p-4">
                    <NewSourcesWizard
                        hideBackButton
                        initialSource={connectingTo}
                        allowedSources={connectableConnectors.map((c: SourceConfig) => c.name)}
                        onComplete={() => setConnectingTo(null)}
                    />
                </LemonCard>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <p className="text-sm text-muted m-0">
                Pull in business context like revenue, usage, and support so agents can connect it to product behavior.
                No ETL; PostHog syncs directly. 1M rows synced free every month.
            </p>

            {connectedConnectors.length > 0 && (
                <div className="flex flex-col gap-2">
                    {connectedConnectors.map((connector: SourceConfig) => (
                        <div
                            key={connector.name}
                            className="flex items-center gap-3 p-3 rounded-lg border border-success bg-success-highlight"
                        >
                            <SourceIcon type={connector.name} size="small" disableTooltip />
                            <span className="flex-1 min-w-0 font-medium text-sm truncate">
                                {connector.label ?? connector.name}
                            </span>
                            <LemonTag type="success" icon={<IconCheckCircle />}>
                                Connected
                            </LemonTag>
                        </div>
                    ))}
                </div>
            )}

            <LemonInput type="search" placeholder="Search sources" value={search} onChange={setSearch} />

            {pickerConnectors.length > 0 ? (
                <div className="flex flex-col gap-2">
                    {pickerConnectors.map((connector: SourceConfig) => (
                        <button
                            key={connector.name}
                            type="button"
                            onClick={() => setConnectingTo(connector.name)}
                            className="flex items-center gap-3 p-3 rounded-lg border border-primary bg-surface-primary text-left cursor-pointer hover:border-accent"
                        >
                            <SourceIcon type={connector.name} size="small" disableTooltip />
                            <span className="flex-1 min-w-0 font-medium text-sm truncate">
                                {connector.label ?? connector.name}
                            </span>
                            <span className="text-xs text-muted shrink-0">Connect</span>
                        </button>
                    ))}
                </div>
            ) : (
                searchTerm && <p className="text-sm text-muted m-0">No sources match "{search}".</p>
            )}

            {!searchTerm && !showAll && hiddenConnectors.length > 0 && (
                <div>
                    <LemonButton type="secondary" size="small" icon={<IconPlus />} onClick={() => setShowAll(true)}>
                        Show {hiddenConnectors.length} more source{hiddenConnectors.length === 1 ? '' : 's'}
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
