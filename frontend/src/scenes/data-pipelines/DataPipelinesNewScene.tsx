import { kea, path, props, selectors, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { capitalizeFirstLetter } from 'lib/utils'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { dataPipelinesNewSceneLogicType } from './DataPipelinesNewSceneType'
import { nonHogFunctionTemplatesLogic } from './utils/nonHogFunctionTemplatesLogic'

export type DataPipelinesNewSceneProps = {
    kind: 'transformation' | 'destination' | 'source' | 'site_app'
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
                    },
                    {
                        key: [Scene.DataPipelines, kind],
                        name: capitalizeFirstLetter(kind) + 's',
                        path: urls.dataPipelines(kind),
                    },
                    {
                        key: Scene.DataPipelinesNew,
                        name: 'New',
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

    const { hogFunctionTemplatesDataWarehouseSources, hogFunctionTemplatesBatchExports } =
        useValues(nonHogFunctionTemplatesLogic)

    if (kind === 'transformation') {
        return <HogFunctionTemplateList type="transformation" />
    }
    if (kind === 'destination') {
        return <HogFunctionTemplateList type="destination" manualTemplates={hogFunctionTemplatesBatchExports} />
    }
    if (kind === 'site_app') {
        return <HogFunctionTemplateList type="site_app" />
    }

    if (kind === 'source') {
        return (
            <HogFunctionTemplateList type="source_webhook" manualTemplates={hogFunctionTemplatesDataWarehouseSources} />
        )
    }

    return <NotFound object="Data pipeline new options" />
}
