import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { autoresearchLogic } from './autoresearchLogic'
import { AutoresearchModelCard } from './AutoresearchModelCard'
import { autoresearchEmptyState } from './emptyState/autoresearchEmptyState'

export const scene: SceneExport = {
    component: AutoresearchScene,
    logic: autoresearchLogic,
    productKey: ProductKey.AUTORESEARCH,
    emptyState: autoresearchEmptyState,
}

export function AutoresearchScene(): JSX.Element {
    const isEnabled = useFeatureFlag('AUTORESEARCH')
    const { pipelines, pipelinesLoading, pipelinesLoadFailed } = useValues(autoresearchLogic)
    const { loadPipelines } = useActions(autoresearchLogic)

    if (!isEnabled) {
        return <NotFound object="Autoresearch" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Autoresearch].name ?? 'Autoresearch'}
                description={sceneConfigurations[Scene.Autoresearch].description}
                resourceType={{
                    type: sceneConfigurations[Scene.Autoresearch].iconType ?? 'experiment',
                }}
                actions={
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        size="small"
                        to={urls.autoresearchNew()}
                        data-attr="autoresearch-new-model"
                    >
                        New model
                    </LemonButton>
                }
            />

            {pipelinesLoadFailed && !pipelinesLoading && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Retry',
                        onClick: () => loadPipelines(),
                        'data-attr': 'autoresearch-list-retry',
                    }}
                >
                    Couldn't load your models. Try again, and if it keeps happening contact support.
                </LemonBanner>
            )}
            {!(pipelinesLoadFailed && pipelines.length === 0) && (
                <div className="@container">
                    <div className="grid grid-cols-1 @2xl:grid-cols-2 @5xl:grid-cols-3 gap-4">
                        {pipelinesLoading && pipelines.length === 0
                            ? Array.from({ length: 3 }, (_, i) => <LemonSkeleton key={i} className="h-48" />)
                            : pipelines.map((pipeline) => (
                                  <AutoresearchModelCard key={pipeline.id} pipeline={pipeline} />
                              ))}
                    </div>
                    {!pipelinesLoading && pipelines.length === 0 && (
                        <p className="text-secondary">No models yet. Create one to start predicting.</p>
                    )}
                </div>
            )}
        </SceneContent>
    )
}
