import { LemonTag, Link, LemonButtonWithSideAction, LemonButton } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ProductKey } from '~/types'
import { DataWarehouseTablesContainer } from './DataWarehouseTables'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataWarehousePageTabs, DataWarehouseTab } from '../DataWarehousePageTabs'
import SourceModal from './SourceModal'
import { IconSettings } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseSceneLogic,
}

export function DataWarehouseExternalScene(): JSX.Element {
    const { shouldShowEmptyState, shouldShowProductIntroduction, isSourceModalOpen } =
        useValues(dataWarehouseSceneLogic)
    const { toggleSourceModal } = useActions(dataWarehouseSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div>
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Data Warehouse
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
                buttons={
                    featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_EXTERNAL_LINK] ? (
                        <LemonButtonWithSideAction
                            type="primary"
                            sideAction={{
                                icon: <IconSettings />,
                                onClick: () => router.actions.push(urls.dataWarehouseSettings()),
                                'data-attr': 'saved-insights-new-insight-dropdown',
                            }}
                            data-attr="new-data-warehouse-easy-link"
                            key={'new-data-warehouse-easy-link'}
                            onClick={() => toggleSourceModal()}
                        >
                            Link Source
                        </LemonButtonWithSideAction>
                    ) : !(shouldShowProductIntroduction || shouldShowEmptyState) ? (
                        <LemonButton type="primary" to={urls.dataWarehouseTable()} data-attr="new-data-warehouse-table">
                            New Table
                        </LemonButton>
                    ) : undefined
                }
                caption={
                    <div>
                        These are external data sources you can query under SQL insights with{' '}
                        <Link to="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </Link>
                        . Connect your own tables from S3 to query data from outside posthog.{' '}
                        <Link to="https://posthog.com/docs/data/data-warehouse">Learn more</Link>
                    </div>
                }
            />
            <DataWarehousePageTabs tab={DataWarehouseTab.External} />
            {(shouldShowProductIntroduction || shouldShowEmptyState) && (
                <ProductIntroduction
                    productName={'Data Warehouse'}
                    thingName={'data warehouse table'}
                    description={
                        'Bring your production database, revenue data, CRM contacts or any other data into PostHog.'
                    }
                    action={() =>
                        featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE_EXTERNAL_LINK]
                            ? toggleSourceModal()
                            : router.actions.push(urls.dataWarehouseTable())
                    }
                    isEmpty={shouldShowEmptyState}
                    docsURL="https://posthog.com/docs/data/data-warehouse"
                    productKey={ProductKey.DATA_WAREHOUSE}
                />
            )}
            {!shouldShowEmptyState && <DataWarehouseTablesContainer />}
            <SourceModal isOpen={isSourceModalOpen} onClose={toggleSourceModal} />
        </div>
    )
}
