import { LemonButton, LemonButtonWithSideAction, LemonTag } from '@posthog/lemon-ui'
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

export const scene: SceneExport = {
    component: DataWarehouseExternalScene,
    logic: dataWarehouseSceneLogic,
}

export function DataWarehouseExternalScene(): JSX.Element {
    const { shouldShowEmptyState, shouldShowProductIntroduction, isSourceModalOpen } =
        useValues(dataWarehouseSceneLogic)
    const { toggleSourceModal } = useActions(dataWarehouseSceneLogic)

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
                buttons={[
                    !shouldShowProductIntroduction ? (
                        <LemonButton
                            type="secondary"
                            to={urls.dataWarehouseTable('new')}
                            data-attr="new-data-warehouse-table"
                            key={'new-data-warehouse-table'}
                        >
                            Manual Link
                        </LemonButton>
                    ) : undefined,
                    <LemonButtonWithSideAction
                        type="primary"
                        sideAction={{
                            icon: <IconSettings />,
                            onClick: () => router.actions.push(urls.dataWarehouseSettings()),
                            'data-attr': 'saved-insights-new-insight-dropdown',
                        }}
                        data-attr="new-data-warehouse-easy-link"
                        key={'new-data-warehouse-easy-link'}
                        onClick={toggleSourceModal}
                    >
                        Link Source
                    </LemonButtonWithSideAction>,
                ]}
                caption={
                    <div>
                        These are external data sources you can query under SQL insights with{' '}
                        <a href="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </a>
                        . Connect your own tables from S3 to query data from outside posthog.{' '}
                        <a href="https://posthog.com/docs/data/data-warehouse">Learn more</a>
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
                    action={() => router.actions.push(urls.dataWarehouseTable('new'))}
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
