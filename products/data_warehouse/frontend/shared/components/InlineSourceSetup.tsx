import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { IconDatabase, IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'

import { availableSourcesLogic } from '../../scenes/NewSourceScene/availableSourcesLogic'
import { NewSourcesWizard } from '../../scenes/NewSourceScene/NewSourceScene'
import { sourceWizardLogic } from '../../scenes/NewSourceScene/sourceWizardLogic'
import { DataWarehouseWizardBlock } from './DataWarehouseWizardBlock'
import { SourceIcon } from './SourceIcon'

export type InlineSourceSetupView = 'selection' | 'connecting'

interface SourceItem {
    id: ExternalDataSourceType
    label: string
}

export interface InlineSourceSetupProps {
    /** Callback when source connection is completed */
    onComplete?: () => void
    /** When true, show only featured sources initially with an expand option to show all */
    featured?: boolean
    /** Custom title for the source selection. Defaults to the live source count. */
    title?: string
    /** Custom subtitle for the source selection */
    subtitle?: string
    /** When true, show the CLI wizard block as a fast path above the source grid (cloud/dev only) */
    showWizard?: boolean
    /** Pre-select all syncable tables with smart defaults so the user can sync in one click */
    autoConfigureTables?: boolean
}

function InternalInlineSourceSetup({
    onComplete,
    featured = false,
    title,
    subtitle = 'Choose a source to import data from',
    showWizard = false,
    autoConfigureTables = false,
}: InlineSourceSetupProps): JSX.Element {
    const { connectors } = useValues(sourceWizardLogic)
    const { onClear } = useActions(sourceWizardLogic)
    const { searchParams, location } = useValues(router)
    const { replace } = useActions(router)

    const [currentView, setCurrentView] = useState<InlineSourceSetupView>('selection')
    const [selectedSource, setSelectedSource] = useState<ExternalDataSourceType | null>(null)
    const [expanded, setExpanded] = useState(!featured)
    const [searchQuery, setSearchQuery] = useState('')

    // Filter out unreleased sources
    const availableConnectors = connectors.filter((c: SourceConfig) => !c.unreleasedSource)

    // Resume an OAuth round-trip: an OAuth source redirects the whole page to the provider and
    // back to this onboarding URL with ?kind=<source>. On mount, re-open the wizard for that
    // source so the user lands back where they left off (credentials are restored by the wizard
    // from the state saved before the redirect). Runs once — subsequent picks use the grid.
    useEffect(() => {
        const kind = searchParams.kind
        if (!kind) {
            return
        }
        const match = availableConnectors.find((c) => c.name.toLowerCase() === String(kind).toLowerCase())
        if (match) {
            setSelectedSource(match.name)
            setCurrentView('connecting')
        }
        // Consume the param so a later remount (refresh, back-navigation, cancel) doesn't force the
        // wizard back open after the connection has already been handled.
        const { kind: _kind, ...restParams } = searchParams
        replace(location.pathname, restParams)
        // oxlint-disable-next-line react-hooks/exhaustive-deps
    }, [])
    const featuredSources = availableConnectors.filter((c: SourceConfig) => c.featured)
    const hiddenSources = availableConnectors.filter((c: SourceConfig) => !c.featured)

    const trimmedQuery = searchQuery.trim().toLowerCase()
    const isSearching = trimmedQuery.length > 0
    // While searching, match across every source — the featured/expand split only applies
    // to the default (unsearched) view.
    const sourcesToShow = isSearching
        ? availableConnectors.filter((c: SourceConfig) => (c.label ?? c.name).toLowerCase().includes(trimmedQuery))
        : expanded
          ? availableConnectors
          : featuredSources

    const sourceItems: SourceItem[] = sourcesToShow.map((source: SourceConfig) => ({
        id: source.name,
        label: source.label ?? source.name,
    }))

    const effectiveTitle = title ?? `Choose from ${availableConnectors.length} sources`

    const handleSourceSelect = (sourceId: ExternalDataSourceType): void => {
        setSelectedSource(sourceId)
        setCurrentView('connecting')
    }

    const handleFormSuccess = (): void => {
        setCurrentView('selection')
        setSelectedSource(null)
        onClear()
        onComplete?.()
    }

    const handleBack = (): void => {
        setCurrentView('selection')
        setSelectedSource(null)
        onClear()
    }

    return (
        <div className="space-y-6">
            {/* Source Selection */}
            {currentView === 'selection' && (
                <LemonCard hoverEffect={false}>
                    <div className="space-y-4">
                        <div className="flex items-center gap-3">
                            <div className="flex items-center justify-center w-12 h-12 rounded-full bg-white border border-primary">
                                <IconDatabase className="w-7 h-7" style={{ color: 'var(--primary-3000)' }} />
                            </div>
                            <div>
                                <h4 className="text-lg font-semibold">{effectiveTitle}</h4>
                                <p className="text-sm text-muted-alt">{subtitle}</p>
                            </div>
                        </div>

                        {showWizard && <DataWarehouseWizardBlock />}

                        <LemonInput
                            type="search"
                            placeholder="Search sources..."
                            value={searchQuery}
                            onChange={setSearchQuery}
                            fullWidth
                            autoFocus
                        />

                        {sourceItems.length > 0 ? (
                            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                                {sourceItems.map((source) => (
                                    <div
                                        key={source.id}
                                        className="flex items-center gap-3 p-3 rounded-lg border border-border bg-bg-light cursor-pointer"
                                        onClick={() => handleSourceSelect(source.id)}
                                    >
                                        <SourceIcon type={source.id} size="small" disableTooltip />
                                        <span className="font-medium text-sm">{source.label}</span>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="text-sm text-muted-alt text-center py-4">
                                No sources match "{searchQuery.trim()}".
                            </p>
                        )}

                        {!isSearching && featured && !expanded && hiddenSources.length > 0 && (
                            <div className="flex justify-center pt-2">
                                <LemonButton
                                    type="secondary"
                                    icon={<IconPlus />}
                                    onClick={() => setExpanded(true)}
                                    size="small"
                                >
                                    Show {hiddenSources.length} more source
                                    {hiddenSources.length !== 1 ? 's' : ''}
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </LemonCard>
            )}

            {/* Source Connection Wizard */}
            {currentView === 'connecting' && selectedSource && (
                <LemonCard hoverEffect={false}>
                    <div className="space-y-4">
                        <div className="flex items-center justify-between mb-4">
                            <LemonButton type="secondary" size="small" onClick={handleBack}>
                                ← Back to sources
                            </LemonButton>
                        </div>
                        <NewSourcesWizard
                            hideBackButton
                            onComplete={handleFormSuccess}
                            allowedSources={availableConnectors.map((c: SourceConfig) => c.name)}
                            initialSource={selectedSource}
                            autoConfigureTables={autoConfigureTables}
                        />
                    </div>
                </LemonCard>
            )}
        </div>
    )
}

export function InlineSourceSetup(props: InlineSourceSetupProps): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <LemonSkeleton />
    }

    return (
        <BindLogic logic={sourceWizardLogic} props={{ availableSources }}>
            <InternalInlineSourceSetup {...props} />
        </BindLogic>
    )
}
