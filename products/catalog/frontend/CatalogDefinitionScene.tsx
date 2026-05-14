import { BindLogic, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { STATUS_COLOR, STATUS_LABEL } from './catalogConstants'
import { CatalogDefinitionForm } from './CatalogDefinitionForm'
import { CatalogDefinitionSceneLogicProps, catalogDefinitionSceneLogic } from './catalogDefinitionSceneLogic'

type DefinitionTab = 'overview' | 'lineage' | 'usage' | 'history' | 'discuss'

export const scene: SceneExport<CatalogDefinitionSceneLogicProps> = {
    component: CatalogDefinitionScene,
    logic: catalogDefinitionSceneLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id || '' }),
    productKey: ProductKey.CATALOG,
}

export function CatalogDefinitionScene({ id }: CatalogDefinitionSceneLogicProps): JSX.Element {
    return (
        <BindLogic logic={catalogDefinitionSceneLogic} props={{ id }}>
            <CatalogDefinitionSceneContent />
        </BindLogic>
    )
}

function CatalogDefinitionSceneContent(): JSX.Element {
    const { definition, definitionLoading } = useValues(catalogDefinitionSceneLogic)
    const [activeTab, setActiveTab] = useState<DefinitionTab>('overview')

    if (definitionLoading && !definition) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-8 w-64" />
                <LemonSkeleton className="h-4 w-96" />
            </SceneContent>
        )
    }

    if (!definition) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Definition not found"
                    description="The catalog definition you're looking for doesn't exist or has been deleted."
                    resourceType={{ type: 'data_warehouse' }}
                />
            </SceneContent>
        )
    }

    const tabs: LemonTab<DefinitionTab>[] = [
        { key: 'overview', label: 'Overview', content: <CatalogDefinitionForm /> },
        { key: 'lineage', label: 'Lineage', tooltip: 'Coming soon', content: <ComingSoonTab label="Lineage" /> },
        { key: 'usage', label: 'Usage', tooltip: 'Coming soon', content: <ComingSoonTab label="Usage" /> },
        { key: 'history', label: 'History', tooltip: 'Coming soon', content: <ComingSoonTab label="History" /> },
        { key: 'discuss', label: 'Discuss', tooltip: 'Coming soon', content: <ComingSoonTab label="Discuss" /> },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={definition.name}
                description={`${definition.kind} · ${definition.columns.length} column${
                    definition.columns.length === 1 ? '' : 's'
                }`}
                resourceType={{ type: 'data_warehouse' }}
                actions={
                    <LemonTag type={STATUS_COLOR[definition.status] ?? 'default'}>
                        {STATUS_LABEL[definition.status] ?? definition.status}
                    </LemonTag>
                }
            />
            <LemonTabs activeKey={activeTab} onChange={setActiveTab} tabs={tabs} />
        </SceneContent>
    )
}

function ComingSoonTab({ label }: { label: string }): JSX.Element {
    return <LemonBanner type="info">{label} view is coming soon.</LemonBanner>
}
