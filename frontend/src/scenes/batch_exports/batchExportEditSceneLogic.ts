import { connect, kea, key, path, props, selectors } from 'kea'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { BatchExportsEditLogicProps } from './batchExportEditLogic'
import type { batchExportsEditSceneLogicType } from './batchExportEditSceneLogicType'
import { batchExportLogic } from './batchExportLogic'

export const batchExportsEditSceneLogic = kea<batchExportsEditSceneLogicType>([
    props({} as BatchExportsEditLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'batch_exports', 'batchExportsEditSceneLogic', key]),
    connect((props: BatchExportsEditLogicProps) => ({
        values: [batchExportLogic(props), ['batchExportConfig']],
    })),

    selectors({
        id: [() => [(_, props) => props], (props): string => props.id],
        breadcrumbs: [
            (s) => [s.batchExportConfig, s.id],
            (config, id): Breadcrumb[] => [
                {
                    key: Scene.BatchExports,
                    name: 'Batch Exports',
                    path: urls.batchExports(),
                },
                ...(id === 'new'
                    ? [
                          {
                              key: 'new',
                              name: 'New',
                          },
                      ]
                    : [
                          {
                              key: config?.id || 'loading',
                              name: config?.name,
                              path: config?.id ? urls.batchExport(config.id) : undefined,
                          },
                          {
                              key: 'edit',
                              name: 'Edit',
                          },
                      ]),
            ],
        ],
    }),
])
