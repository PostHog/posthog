import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { IconSettings } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { DataWarehousePageTabs, DataWarehouseTab } from '../DataWarehousePageTabs'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'
import { DataWarehouseTablesContainer } from './DataWarehouseTables'
import SourceModal from './SourceModal'

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
                buttons={
                    <LemonButton
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
                    </LemonButton>
                }
                caption={
                    <div>
                        These are external data sources you can query under SQL insights with{' '}
                        <Link to="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </Link>
                        . Connect your own tables from S3 to query data from outside PostHog.{' '}
                        <Link to="https://posthog.com/docs/data/data-warehouse">Learn more</Link>
                    </div>
                }
            />
            <DataWarehousePageTabs tab={DataWarehouseTab.External} />
            {(shouldShowProductIntroduction || shouldShowEmptyState) && (
                <ProductIntroduction
                    productName={'Data Warehouse'}
                    thingName={'table'}
                    description={
                        'Bring your production database, revenue data, CRM contacts or any other data into PostHog.'
                    }
                    action={toggleSourceModal}
                    isEmpty={shouldShowEmptyState}
                    docsURL="https://posthog.com/docs/data/data-warehouse"
                    productKey={ProductKey.DATA_WAREHOUSE}
                />
            )}
            {!shouldShowEmptyState && <DataWarehouseTablesContainer />}
            <SourceModal isOpen={isSourceModalOpen} onClose={() => toggleSourceModal(false)} />
        </div>
    )
}
