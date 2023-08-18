import { connect, kea, key, path, props, selectors } from 'kea'

import { Breadcrumb } from '~/types'

import { urls } from 'scenes/urls'

import { batchExportLogic } from './batchExportLogic'
import { BatchExportsEditLogicProps } from './batchExportEditLogic'

import type { batchExportsEditSceneLogicType } from './batchExportEditSceneLogicType'

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
                    name: 'Batch Exports',
                    path: urls.batchExports(),
                },
                ...(id === 'new'
                    ? [
                          {
                              name: 'New',
                          },
                      ]
                    : [
                          {
                              name: config?.name ?? 'Loading',
                              path: config?.id ? urls.batchExport(config.id) : undefined,
                          },

                          {
                              name: 'Edit',
                          },
                      ]),
            ],
        ],
    }),
])
