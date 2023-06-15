import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { userLogic } from 'scenes/userLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { surveysLogic } from './tablesLogic'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { DatabaseTables } from 'scenes/data-management/database/DatabaseTables'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ProductKey } from '~/types'

export const scene: SceneExport = {
    component: Surveys,
    logic: surveysLogic,
}

export enum SurveysTabs {
    All = 'all',
    Yours = 'yours',
    Archived = 'archived',
}

export function Surveys(): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <div className="mt-10">
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
                        to={urls.dataWarehouseTable('new')}
                        data-attr="new-data-warehouse-table"
                    >
                        New Table
                    </LemonButton>
                }
            />
            {!user?.has_seen_product_intro_for?.[ProductKey.DATA_WAREHOUSE] && (
                <ProductIntroduction
                    productName={'Data Warehouse'}
                    thingName={'data warehouse table'}
                    description={
                        'Bring your production database, revenue data, CRM contacts or any other data into PostHog.'
                    }
                    action={() => router.actions.push(urls.dataWarehouseTable('new'))}
                    isEmpty={true}
                    productKey={ProductKey.DATA_WAREHOUSE}
                />
            )}
            <DatabaseTables />
        </div>
    )
}
