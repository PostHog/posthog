import { BindLogic, useValues } from 'kea'

import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { CatalogDefinitionSceneLogicProps, catalogDefinitionSceneLogic } from './catalogDefinitionSceneLogic'

const STATUS_COLOR: Record<string, 'default' | 'primary' | 'success' | 'warning' | 'danger'> = {
    proposed: 'default',
    approved: 'primary',
    official: 'success',
    drift: 'warning',
}

const STATUS_LABEL: Record<string, string> = {
    proposed: 'AI-proposed',
    approved: 'Approved',
    official: 'Official',
    drift: 'Drift detected',
}

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

    return (
        <SceneContent>
            <SceneTitleSection
                name={definition.name}
                description={definition.description ?? 'No description yet.'}
                resourceType={{ type: 'catalog' }}
                actions={
                    <LemonTag type={STATUS_COLOR[definition.status] ?? 'default'}>
                        {STATUS_LABEL[definition.status] ?? definition.status}
                    </LemonTag>
                }
            />
            <div className="text-sm text-secondary">
                Kind: <span className="font-mono">{definition.kind}</span>
                {definition.business_domain && (
                    <>
                        {' '}
                        · Domain: <span className="font-mono">{definition.business_domain}</span>
                    </>
                )}{' '}
                · {definition.columns.length} column{definition.columns.length === 1 ? '' : 's'}
            </div>
        </SceneContent>
    )
}
