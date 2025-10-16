import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconGear } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DataWarehouseSourceIcon } from 'scenes/data-warehouse/settings/DataWarehouseSourceIcon'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { FEATURE_FLAGS } from '~/lib/constants'
import { ExternalDataSource } from '~/types'

import { useSortedPaginatedList } from '../../hooks/useSortedPaginatedList'
import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import {
    MAX_ITEMS_TO_SHOW,
    NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS,
    VALID_NATIVE_MARKETING_SOURCES,
} from '../../logic/utils'
import { AddSourceDropdown } from './AddSourceDropdown'
import { ListDisplay } from './ListDisplay'
import { ItemName, PaginationControls } from './PaginationControls'
import { StatusIcon } from './StatusIcon'

export function NativeExternalDataSourceConfiguration(): JSX.Element {
    const { nativeSources, loading } = useValues(marketingAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const validNativeSources = featureFlags[FEATURE_FLAGS.META_ADS_DWH]
        ? VALID_NATIVE_MARKETING_SOURCES
        : VALID_NATIVE_MARKETING_SOURCES.filter((source) => source !== 'MetaAds')

    // Helper functions to reduce duplication
    const getRequiredFields = (sourceType: string): string[] => {
        return (
            NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS[
                sourceType as keyof typeof NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS
            ] || []
        )
    }

    const isFieldSyncing = (source: ExternalDataSource, fieldName: string): boolean => {
        if (!source.schemas) {
            return false
        }
        const schema = source.schemas.find((schema) => schema.name === fieldName)
        return schema?.should_sync ?? false
    }

    const getSourceSyncInfo = (
        source: ExternalDataSource
    ): { syncingTables: string[]; tablesToSync: string[]; totalRequired: number; syncingCount: number } => {
        const requiredFields = getRequiredFields(source.source_type)
        if (!requiredFields.length || !source.schemas) {
            return { syncingTables: [], tablesToSync: [], totalRequired: 0, syncingCount: 0 }
        }

        const syncingTables = requiredFields.filter((field) => isFieldSyncing(source, field))
        const tablesToSync = requiredFields.filter((field) => !isFieldSyncing(source, field))

        return {
            syncingTables,
            tablesToSync,
            totalRequired: requiredFields.length,
            syncingCount: syncingTables.length,
        }
    }

    const isSourceFullyConfigured = (source: ExternalDataSource): boolean => {
        const { syncingCount, totalRequired } = getSourceSyncInfo(source)
        return totalRequired > 0 && syncingCount === totalRequired
    }

    const {
        displayedItems: displayedSources,
        sortedItems: sourcesToUse,
        hasMoreItems: hasMoreSources,
        showAll,
        setShowAll,
    } = useSortedPaginatedList({
        items: nativeSources,
        maxItemsToShow: MAX_ITEMS_TO_SHOW,
        getId: (source) => source.id,
        isItemConfigured: isSourceFullyConfigured,
    })

    const getSourceStatus = (source: ExternalDataSource): { isConfigured: boolean; message: string } => {
        if (!source.schemas || source.schemas.length === 0) {
            return { isConfigured: false, message: 'No schemas configured' }
        }

        const { syncingCount, totalRequired, tablesToSync } = getSourceSyncInfo(source)

        if (totalRequired === 0) {
            return { isConfigured: false, message: 'Unknown source type' }
        }

        if (syncingCount === totalRequired) {
            return { isConfigured: true, message: 'Ready to use! All required fields are syncing.' }
        }

        const missingCount = totalRequired - syncingCount
        return {
            isConfigured: false,
            message: `${missingCount} field${missingCount > 1 ? 's' : ''} need to be synced: ${tablesToSync.join(
                ', '
            )}`,
        }
    }

    return (
        <SceneSection
            title="Native data warehouse sources configuration"
            description="Configure data warehouse sources to display marketing analytics in PostHog. You'll need to sync the required tables for each source to enable the functionality."
        >
            <PaginationControls
                hasMoreItems={hasMoreSources}
                showAll={showAll}
                onToggleShowAll={() => setShowAll(!showAll)}
                totalCount={sourcesToUse.length}
                itemName={ItemName.Sources}
                maxItemsToShow={MAX_ITEMS_TO_SHOW}
                additionalControls={
                    <AddSourceDropdown<ExternalDataSource['source_type']>
                        sources={validNativeSources}
                        onSourceAdd={(source) => {
                            router.actions.push(urls.dataWarehouseSourceNew(source))
                        }}
                    />
                }
            />
            <LemonTable
                rowKey={(item) => item.id}
                loading={loading}
                dataSource={displayedSources}
                columns={[
                    {
                        key: 'source',
                        title: '',
                        width: 0,
                        render: (_, item: ExternalDataSource): JSX.Element => {
                            return <DataWarehouseSourceIcon type={item.source_type} />
                        },
                    },
                    {
                        key: 'prefix',
                        title: 'Source',
                        render: (_, item: ExternalDataSource): JSX.Element => {
                            return (
                                <Link to={urls.dataWarehouseSource(`managed-${item.id}`)}>
                                    {item.prefix || item.source_type}
                                </Link>
                            )
                        },
                    },
                    {
                        key: 'syncing',
                        title: 'Tables Syncing',
                        width: 150,
                        render: (_, item: ExternalDataSource): JSX.Element => {
                            const { syncingTables } = getSourceSyncInfo(item)
                            return <ListDisplay list={syncingTables} />
                        },
                    },
                    {
                        key: 'to_sync',
                        title: 'Tables to Sync',
                        width: 150,
                        render: (_, item: ExternalDataSource): JSX.Element => {
                            const { tablesToSync } = getSourceSyncInfo(item)
                            return <ListDisplay list={tablesToSync} />
                        },
                    },
                    {
                        key: 'status',
                        title: 'Status',
                        width: 80,
                        render: (_, item: ExternalDataSource): JSX.Element => {
                            const { isConfigured, message } = getSourceStatus(item)

                            if (isConfigured) {
                                return <StatusIcon status="success" message={message} />
                            }
                            const hasAnySchemas = item.schemas && item.schemas.length > 0
                            return <StatusIcon status={hasAnySchemas ? 'warning' : 'error'} message={message} />
                        },
                    },
                    {
                        key: 'actions',
                        title: 'Actions',
                        width: 80,
                        render: (_, item: ExternalDataSource): JSX.Element => {
                            return (
                                <LemonButton
                                    icon={<IconGear />}
                                    size="small"
                                    to={urls.dataWarehouseSource(`managed-${item.id}`)}
                                    tooltip="Configure source schemas"
                                />
                            )
                        },
                    },
                ]}
            />
        </SceneSection>
    )
}
