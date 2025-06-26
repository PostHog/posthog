import { actions, kea, key, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { NotFound } from 'lib/components/NotFound'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { DataPipelinesSelfManagedSource } from 'scenes/data-pipelines/DataPipelinesSelfManagedSource'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineTab } from '~/types'

import type { dataWarehouseSourceSceneLogicType } from './DataWarehouseSourceSceneType'
import { Schemas } from './source/Schemas'
import { SourceConfiguration } from './source/SourceConfiguration'
import { Syncs } from './source/Syncs'

const DATA_WAREHOUSE_SOURCE_SCENE_TABS = ['schemas', 'syncs', 'configuration'] as const
export type DataWarehouseSourceSceneTab = (typeof DATA_WAREHOUSE_SOURCE_SCENE_TABS)[number]

export interface DataWarehouseSourceSceneProps {
    id: string
}

export const dataWarehouseSourceSceneLogic = kea<dataWarehouseSourceSceneLogicType>([
    props({} as DataWarehouseSourceSceneProps),
    key(({ id }: DataWarehouseSourceSceneProps) => id),
    path((key) => ['scenes', 'data-warehouse', 'dataWarehouseSourceSceneLogic', key]),
    actions({
        setCurrentTab: (tab: DataWarehouseSourceSceneTab) => ({ tab }),
        setBreadcrumbName: (name: string) => ({ name }),
    }),
    reducers(() => ({
        currentTab: [
            'configuration' as DataWarehouseSourceSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
        breadcrumbName: [
            'Source' as string,
            {
                setBreadcrumbName: (_, { name }) => name,
            },
        ],
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props) => props],
        breadcrumbs: [
            (s) => [s.breadcrumbName],
            (breadcrumbName): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Pipeline,
                        name: 'Data pipelines',
                        path: urls.pipeline(PipelineTab.Overview),
                    },
                    {
                        key: Scene.Pipeline,
                        name: `Sources`,
                        path: urls.pipeline(PipelineTab.Sources),
                    },
                    {
                        key: Scene.DataWarehouseSource,
                        name: breadcrumbName,
                    },
                ]
            },
        ],
    }),
    actionToUrl(({ props, values }) => ({
        setCurrentTab: () => {
            return urls.dataWarehouseSource(props.id, values.currentTab)
        },
    })),
    urlToAction(({ actions, values }) => {
        return {
            [urls.dataWarehouseSource(':id', ':tab')]: (params): void => {
                let possibleTab = (params.tab ?? 'configuration') as DataWarehouseSourceSceneTab

                if (params.id?.startsWith('self-managed-')) {
                    possibleTab = 'configuration' // This only has one tab
                }

                const tab = DATA_WAREHOUSE_SOURCE_SCENE_TABS.includes(possibleTab) ? possibleTab : 'configuration'
                if (tab !== values.currentTab) {
                    actions.setCurrentTab(tab)
                }
            },
        }
    }),
])

export const scene: SceneExport = {
    component: DataWarehouseSourceScene,
    logic: dataWarehouseSourceSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof dataWarehouseSourceSceneLogic)['props'] => ({ id }),
}

export function DataWarehouseSourceScene(): JSX.Element {
    const { currentTab, logicProps } = useValues(dataWarehouseSourceSceneLogic)
    const { setCurrentTab } = useActions(dataWarehouseSourceSceneLogic)
    const { id } = logicProps

    if (!id) {
        return <NotFound object="Data warehouse source" />
    }

    const cleanId = id.replace('self-managed-', '').replace('managed-', '')

    const tabs: LemonTab<DataWarehouseSourceSceneTab>[] = id.startsWith('managed-')
        ? [
              {
                  label: 'Schemas',
                  key: 'schemas',
                  content: <Schemas id={cleanId} />,
              },
              {
                  label: 'Syncs',
                  key: 'syncs',
                  content: <Syncs id={cleanId} />,
              },
              {
                  label: 'Configuration',
                  key: 'configuration',
                  content: <SourceConfiguration id={cleanId} />,
              },
          ]
        : [
              {
                  label: 'Configuration',
                  key: 'configuration',
                  content: <DataPipelinesSelfManagedSource id={cleanId} />,
              },
          ]

    return <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} />
}
