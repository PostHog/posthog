import { BindLogic, useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { NewMetricModal } from './components/NewMetricModal'
import { DataCatalogTab, dataCatalogSceneLogic } from './dataCatalogSceneLogic'
import { metricsLogic } from './metricsLogic'
import { MetricsTab } from './tabs/MetricsTab'

export const scene: SceneExport = {
    component: DataCatalogScene,
    logic: dataCatalogSceneLogic,
    productKey: ProductKey.DATA_CATALOG,
}

function TabPlaceholder({ label }: { label: string }): JSX.Element {
    return <p className="text-secondary">{label} are coming soon.</p>
}

export function DataCatalogScene(): JSX.Element {
    const { activeTab } = useValues(dataCatalogSceneLogic)
    const { setActiveTab } = useActions(dataCatalogSceneLogic)
    const { openNewMetricModal } = useActions(metricsLogic)

    const tabs: LemonTab<DataCatalogTab>[] = [
        {
            key: 'metrics',
            label: 'Metrics',
            content: <MetricsTab />,
            link: urls.dataCatalog(),
        },
        {
            key: 'relationships',
            label: 'Relationships',
            content: <TabPlaceholder label="Relationships" />,
            link: urls.dataCatalog('relationships'),
        },
        {
            key: 'certifications',
            label: 'Certifications',
            content: <TabPlaceholder label="Certifications" />,
            link: urls.dataCatalog('certifications'),
        },
    ]

    return (
        <BindLogic logic={metricsLogic} props={{}}>
            <SceneContent>
                <SceneTitleSection
                    name="Data catalog"
                    description="Review and manage governed metrics, certifications, and relationships for your data."
                    resourceType={{ type: 'data_warehouse' }}
                    actions={
                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlusSmall />}
                            onClick={openNewMetricModal}
                            data-attr="data-catalog-new-metric-button"
                        >
                            New metric
                        </LemonButton>
                    }
                />
                <LemonTabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    data-attr="data-catalog-tabs"
                    tabs={tabs}
                    sceneInset
                />
                <NewMetricModal />
            </SceneContent>
        </BindLogic>
    )
}
