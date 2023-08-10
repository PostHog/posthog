import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'

import {
    BatchExportConfiguration,
    BatchExportDestination,
    BatchExportDestinationS3,
    BatchExportDestinationSnowflake,
    Breadcrumb,
} from '~/types'

import api from 'lib/api'
import { forms } from 'kea-forms'
import { urls } from 'scenes/urls'
import { beforeUnload, router } from 'kea-router'

import type { batchExportsEditLogicType } from './batchExportEditLogicType'
import { dayjs, Dayjs } from 'lib/dayjs'
import { batchExportLogic } from './batchExportLogic'

export type BatchExportsEditLogicProps = {
    id: string | 'new'
}

type BatchExportConfigurationFrom = Omit<BatchExportConfiguration, 'id' | 'destination' | 'start_at' | 'end_at'> &
    Partial<BatchExportDestinationS3['config']> &
    Partial<BatchExportDestinationSnowflake['config']> & {
        destination: 'S3' | 'Snowflake'
        start_at: Dayjs | null
        end_at: Dayjs | null
    }

const formFields = (
    props: BatchExportsEditLogicProps,
    { name, destination, interval, start_at, end_at, paused, ...config }: BatchExportConfigurationFrom
): Record<string, any> => {
    // Important! All fields that are required must be checked here as it is used also to sanitise the existing
    const isNew = props.id === 'new'

    return {
        name: !name ? 'Please enter a name' : '',
        destination: !destination ? 'Please select a destination' : '',
        interval: !interval ? 'Please select a frequency' : '',
        paused: '',
        start_at: '',
        end_at: '',
        ...(destination === 'S3'
            ? {
                  bucket_name: !config.bucket_name ? 'This field is required' : '',
                  region: !config.region ? 'This field is required' : '',
                  prefix: !config.prefix ? 'This field is required' : '',
                  aws_access_key_id: isNew ? (!config.aws_access_key_id ? 'This field is required' : '') : '',
                  aws_secret_access_key: isNew ? (!config.aws_secret_access_key ? 'This field is required' : '') : '',
              }
            : destination === 'Snowflake'
            ? {
                  account: !config.account ? 'This field is required' : '',
                  database: !config.database ? 'This field is required' : '',
                  warehouse: !config.warehouse ? 'This field is required' : '',
                  user: isNew ? (!config.user ? 'This field is required' : '') : '',
                  password: isNew ? (!config.password ? 'This field is required' : '') : '',
                  schema: !config.schema ? 'This field is required' : '',
                  table_name: !config.table_name ? 'This field is required' : '',
                  role: '',
              }
            : {}),
    }
}

export const batchExportsEditLogic = kea<batchExportsEditLogicType>([
    props({} as BatchExportsEditLogicProps),
    key(({ id }) => id),
    path((key) => ['scenes', 'batch_exports', 'batchExportsEditLogic', key]),
    connect((props: BatchExportsEditLogicProps) => ({
        values: [batchExportLogic(props), ['batchExportConfig', 'batchExportConfigLoading']],
        actions: [batchExportLogic(props), ['loadBatchExportConfig', 'loadBatchExportConfigSuccess']],
    })),

    actions({
        cancelEditing: true,
    }),

    forms(({ props }) => ({
        batchExportConfigForm: {
            defaults: {
                name: '',
            } as BatchExportConfigurationFrom,
            errors: (form) => formFields(props, form),
            submit: async ({ name, destination, interval, start_at, end_at, paused, ...config }) => {
                const destinationObject: BatchExportDestination =
                    destination === 'S3'
                        ? {
                              type: 'S3',
                              config: config,
                          }
                        : {
                              type: 'Snowflake',
                              config: config,
                          }

                const data: Omit<BatchExportConfiguration, 'id' | 'created_at'> = {
                    paused,
                    name,
                    interval,
                    start_at,
                    end_at,
                    destination: destinationObject,
                }

                const result =
                    props.id === 'new'
                        ? await api.batchExports.create(data)
                        : await api.batchExports.update(props.id, data)

                await new Promise((resolve) => setTimeout(resolve, 1000))

                router.actions.replace(urls.batchExport(result.id))

                return
            },
        },
    })),

    listeners(({ values, props, actions }) => ({
        cancelEditing: () => {
            if (values.isNew) {
                router.actions.push(urls.batchExports())
            } else {
                router.actions.push(urls.batchExport(props.id))
            }
        },

        loadBatchExportConfigSuccess: ({ batchExportConfig }) => {
            if (!batchExportConfig) {
                return
            }

            const destination = batchExportConfig.destination.type

            const transformedConfig: BatchExportConfigurationFrom = {
                ...batchExportConfig,
                destination,
                start_at: batchExportConfig.start_at ? dayjs(batchExportConfig.start_at) : null,
                end_at: batchExportConfig.end_at ? dayjs(batchExportConfig.end_at) : null,
                ...batchExportConfig.destination.config,
            }

            // Filter out any values that aren't part of our from

            const validFormFields = Object.keys(formFields(props, transformedConfig))

            Object.keys(transformedConfig).forEach((key) => {
                if (!validFormFields.includes(key)) {
                    delete transformedConfig[key]
                }
            })

            actions.resetBatchExportConfigForm(transformedConfig)
        },
    })),

    selectors({
        isNew: [() => [(_, props) => props], (props): boolean => props.id === 'new'],
        breadcrumbs: [
            (s) => [s.batchExportConfig, s.isNew],
            (config, isNew): Breadcrumb[] => [
                {
                    name: 'Batch Exports',
                    path: urls.batchExports(),
                },
                ...(isNew
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

    afterMount(({ values, actions }) => {
        if (!values.isNew) {
            if (values.batchExportConfig) {
                actions.loadBatchExportConfigSuccess(values.batchExportConfig)
            } else {
                actions.loadBatchExportConfig()
            }
        }
    }),

    beforeUnload(({ values }) => ({
        enabled: () => values.batchExportConfigFormChanged,
        message: `Leave?\nChanges you made will be discarded.`,
    })),
])
