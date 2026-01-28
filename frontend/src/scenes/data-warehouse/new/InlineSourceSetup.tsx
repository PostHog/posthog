import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDatabase, IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'

import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'

import { NewSourcesWizard } from './NewSourceWizard'
import { availableSourcesDataLogic } from './availableSourcesDataLogic'
import { sourceWizardLogic } from './sourceWizardLogic'

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
    /** Custom title for the source selection */
    title?: string
    /** Custom subtitle for the source selection */
    subtitle?: string
}

function InternalInlineSourceSetup({
    onComplete,
    featured = false,
    title = 'Connect a data source',
    subtitle = 'Choose a source to import data from',
}: InlineSourceSetupProps): JSX.Element {
    const { connectors } = useValues(sourceWizardLogic)
    const { onClear } = useActions(sourceWizardLogic)

    const [currentView, setCurrentView] = useState<InlineSourceSetupView>('selection')
    const [selectedSource, setSelectedSource] = useState<ExternalDataSourceType | null>(null)
    const [expanded, setExpanded] = useState(!featured)

    // Filter out unreleased sources
    const availableConnectors = connectors.filter((c: SourceConfig) => !c.unreleasedSource)
    const featuredSources = availableConnectors.filter((c: SourceConfig) => c.featured)
    const hiddenSources = availableConnectors.filter((c: SourceConfig) => !c.featured)
    const sourcesToShow = expanded ? availableConnectors : featuredSources

    const sourceItems: SourceItem[] = sourcesToShow.map((source: SourceConfig) => ({
        id: source.name,
        label: source.label ?? source.name,
    }))

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
                                <h4 className="text-lg font-semibold">{title}</h4>
                                <p className="text-sm text-muted-alt">{subtitle}</p>
                            </div>
                        </div>

                        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                            {sourceItems.map((source) => (
                                <div
                                    key={source.id}
                                    className="flex items-center gap-3 p-3 rounded-lg border border-border bg-bg-light cursor-pointer"
                                    onClick={() => handleSourceSelect(source.id)}
                                >
                                    <DataWarehouseSourceIcon type={source.id} size="small" disableTooltip />
                                    <span className="font-medium text-sm">{source.label}</span>
                                </div>
                            ))}
                        </div>

                        {featured && !expanded && hiddenSources.length > 0 && (
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
                        />
                    </div>
                </LemonCard>
            )}
        </div>
    )
}

export function InlineSourceSetup(props: InlineSourceSetupProps): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesDataLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <LemonSkeleton />
    }

    return (
        <BindLogic logic={sourceWizardLogic} props={{ availableSources }}>
            <InternalInlineSourceSetup {...props} />
        </BindLogic>
    )
}
