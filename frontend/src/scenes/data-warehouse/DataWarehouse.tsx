import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { surveysLogic } from './tablesLogic'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useState } from 'react'
import { FEATURE_FLAGS } from 'lib/constants'
import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DatabaseTables } from 'scenes/data-management/database/DatabaseTables'

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
    const { surveys, surveysLoading } = useValues(surveysLogic)
    const [tab, setSurveyTab] = useState(SurveysTabs.All)
    const { featureFlags } = useValues(featureFlagLogic)

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
            <LemonTabs
                activeKey={tab}
                onChange={(newTab) => setSurveyTab(newTab)}
                tabs={[
                    { key: SurveysTabs.All, label: 'All surveys' },
                    { key: SurveysTabs.Archived, label: 'Archived surveys' },
                ]}
            />
            {!surveysLoading && surveys.length === 0 && featureFlags[FEATURE_FLAGS.NEW_EMPTY_STATES] === 'test' ? (
                <ProductEmptyState
                    productName={'Data Warehouse'}
                    thingName={'data-warehouse'}
                    description={
                        'Bring your production database, revenue data, CRM contacts and any other data into PostHog.'
                    }
                    action={() => router.actions.push(urls.dataWarehouseTable('new'))}
                />
            ) : (
                <DatabaseTables />
            )}
        </div>
    )
}
