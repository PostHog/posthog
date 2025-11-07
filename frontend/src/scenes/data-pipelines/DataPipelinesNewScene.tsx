import { kea, path, props, selectors, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { capitalizeFirstLetter } from 'lib/utils'
import { availableSourcesDataLogic } from 'scenes/data-warehouse/new/availableSourcesDataLogic'
import { humanizeHogFunctionType } from 'scenes/hog-functions/hog-function-utils'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Breadcrumb } from '~/types'

import type { dataPipelinesNewSceneLogicType } from './DataPipelinesNewSceneType'
import { DataPipelinesSceneTab } from './DataPipelinesScene'
import { nonHogFunctionTemplatesLogic } from './utils/nonHogFunctionTemplatesLogic'

export type DataPipelinesNewSceneKind = 'transformation' | 'destination' | 'source' | 'site_app'

export type DataPipelinesNewSceneProps = {
    kind: DataPipelinesNewSceneKind
}

export const dataPipelinesNewSceneLogic = kea<dataPipelinesNewSceneLogicType>([
    props({} as DataPipelinesNewSceneProps),
    path(() => ['scenes', 'data-pipelines', 'dataPipelinesNewSceneLogic']),
    selectors({
        logicProps: [() => [(_, props) => props], (props) => props],
        breadcrumbs: [
            () => [(_, props) => props],
            ({ kind }): Breadcrumb[] => {
                return [
                    {
                        key: Scene.DataPipelines,
                        name: 'Data pipelines',
                        path: urls.dataPipelines('overview'),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: [Scene.DataPipelines, kind],
                        name: capitalizeFirstLetter(humanizeHogFunctionType(kind, true)),
                        path: urls.dataPipelines((kind + 's') as DataPipelinesSceneTab),
                        iconType: 'data_pipeline',
                    },
                    {
                        key: Scene.DataPipelinesNew,
                        name: 'New ' + humanizeHogFunctionType(kind),
                        iconType: 'data_pipeline',
                    },
                ]
            },
        ],
    }),
])

export const scene: SceneExport = {
    component: DataPipelinesNewScene,
    logic: dataPipelinesNewSceneLogic,
    paramsToProps: ({ params: { kind } }): (typeof dataPipelinesNewSceneLogic)['props'] => ({
        kind,
    }),
}

export function DataPipelinesNewScene(): JSX.Element {
    const { logicProps } = useValues(dataPipelinesNewSceneLogic)
    const { kind } = logicProps

    const { availableSources, availableSourcesLoading } = useValues(availableSourcesDataLogic)
    const { hogFunctionTemplatesDataWarehouseSources, hogFunctionTemplatesBatchExports } = useValues(
        nonHogFunctionTemplatesLogic({
            availableSources: availableSources ?? {},
        })
    )

    const humanizedKind = humanizeHogFunctionType(kind)

    return (
        <SceneContent>
            <SceneTitleSection
                name={`New ${humanizedKind}`}
                resourceType={{
                    type: 'data_pipeline',
                }}
            />

            {kind === 'transformation' ? (
                <HogFunctionTemplateList type="transformation" />
            ) : kind === 'destination' ? (
                <HogFunctionTemplateList type="destination" manualTemplates={hogFunctionTemplatesBatchExports} />
            ) : kind === 'site_app' ? (
                <HogFunctionTemplateList type="site_app" />
            ) : kind === 'source' ? (
                <HogFunctionTemplateList
                    type="source_webhook"
                    manualTemplates={hogFunctionTemplatesDataWarehouseSources}
                    manualTemplatesLoading={availableSourcesLoading}
                />
            ) : (
                <NotFound object="Data pipeline new options" />
            )}
        </SceneContent>
    )
}
