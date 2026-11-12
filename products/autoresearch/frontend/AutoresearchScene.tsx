import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { autoresearchLogic } from './autoresearchLogic'
import { AutoresearchModelCard } from './AutoresearchModelCard'
import { autoresearchEmptyState } from './emptyState/autoresearchEmptyState'
import { MODEL_LIST_SORT_OPTIONS } from './modelList'

export const scene: SceneExport = {
    component: AutoresearchScene,
    logic: autoresearchLogic,
    productKey: ProductKey.AUTORESEARCH,
    emptyState: autoresearchEmptyState,
}

export function AutoresearchScene(): JSX.Element {
    const isEnabled = useFeatureFlag('AUTORESEARCH')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { pipelines, visiblePipelines, pipelinesLoading, pipelinesLoadFailed, searchTerm, sort } =
        useValues(autoresearchLogic)
    const { loadPipelines, setSearchTerm, setSort } = useActions(autoresearchLogic)

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
                    todayRailNav ? (
                        <Button
                            variant="primary"
                            render={<LinkPrimitive to={urls.autoresearchNew()} />}
                            data-attr="autoresearch-new-model"
                        >
                            <IconPlus />
                            New model
                        </Button>
                    ) : (
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            size="small"
                            to={urls.autoresearchNew()}
                            data-attr="autoresearch-new-model"
                        >
                            New model
                        </LemonButton>
                    )
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
                <div className="@container flex flex-col gap-4">
                    {pipelines.length > 0 && (
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonInput
                                type="search"
                                placeholder="Search by name or event"
                                value={searchTerm}
                                onChange={setSearchTerm}
                                size="small"
                                className="grow max-w-100"
                                data-attr="autoresearch-model-list-search"
                            />
                            <LemonSelect
                                value={sort}
                                onChange={setSort}
                                options={MODEL_LIST_SORT_OPTIONS}
                                size="small"
                                dropdownMatchSelectWidth={false}
                                data-attr="autoresearch-model-list-sort"
                            />
                        </div>
                    )}
                    <div className="grid grid-cols-1 @2xl:grid-cols-2 @5xl:grid-cols-3 gap-4">
                        {pipelinesLoading && pipelines.length === 0
                            ? Array.from({ length: 3 }, (_, i) => <LemonSkeleton key={i} className="h-48" />)
                            : visiblePipelines.map((pipeline) => (
                                  <AutoresearchModelCard key={pipeline.id} pipeline={pipeline} />
                              ))}
                    </div>
                    {!pipelinesLoading && pipelines.length === 0 && (
                        <p className="text-secondary">No models yet. Create one to start predicting.</p>
                    )}
                    {pipelines.length > 0 && visiblePipelines.length === 0 && (
                        <p className="text-secondary">
                            No models match “{searchTerm.trim()}”. Try another name or event, or clear the search.
                        </p>
                    )}
                </div>
            )}
        </SceneContent>
    )
}
