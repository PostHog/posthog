import { BindLogic, useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonBadge } from 'lib/lemon-ui/LemonBadge'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { certificationsLogic } from './certificationsLogic'
import { NewMetricModal } from './components/NewMetricModal'
import { DataCatalogTab, dataCatalogSceneLogic } from './dataCatalogSceneLogic'
import { metricsLogic } from './metricsLogic'
import { relationshipsLogic } from './relationshipsLogic'
import { CertificationsTab } from './tabs/CertificationsTab'
import { MetricsTab } from './tabs/MetricsTab'
import { RelationshipsTab } from './tabs/RelationshipsTab'

export const scene: SceneExport = {
    component: DataCatalogScene,
    logic: dataCatalogSceneLogic,
    productKey: ProductKey.DATA_CATALOG,
}

function TabLabel({ label, count }: { label: string; count: number }): JSX.Element {
    return (
        <span className="flex items-center gap-1">
            {label}
            {count > 0 && <LemonBadge.Number count={count} status="primary" size="small" />}
        </span>
    )
}

export function DataCatalogScene(): JSX.Element {
    const { activeTab } = useValues(dataCatalogSceneLogic)
    const { setActiveTab } = useActions(dataCatalogSceneLogic)
    const { proposedCount: metricsPending } = useValues(metricsLogic)
    const { pendingCount: relationshipsPending } = useValues(relationshipsLogic)
    const { proposedCount: certificationsPending } = useValues(certificationsLogic)
    const { openNewMetricModal: openMetricModal } = useActions(metricsLogic)

    const tabs: LemonTab<DataCatalogTab>[] = [
        {
            key: 'metrics',
            label: <TabLabel label="Metrics" count={metricsPending} />,
            content: <MetricsTab />,
            link: urls.dataCatalog(),
        },
        {
            key: 'relationships',
            label: <TabLabel label="Relationships" count={relationshipsPending} />,
            content: <RelationshipsTab />,
            link: urls.dataCatalog('relationships'),
        },
        {
            key: 'certifications',
            label: <TabLabel label="Certifications" count={certificationsPending} />,
            content: <CertificationsTab />,
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
                            onClick={openMetricModal}
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
