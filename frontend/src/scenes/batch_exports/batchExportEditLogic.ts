import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { beforeUnload, router } from 'kea-router'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    BatchExportConfiguration,
    BatchExportDestination,
    BatchExportDestinationBigQuery,
    BatchExportDestinationPostgres,
    BatchExportDestinationRedshift,
    BatchExportDestinationS3,
    BatchExportDestinationSnowflake,
    Breadcrumb,
} from '~/types'

import type { batchExportsEditLogicType } from './batchExportEditLogicType'
import { batchExportLogic } from './batchExportLogic'

export type BatchExportsEditLogicProps = {
    id: string
}

export type BatchExportConfigurationForm = Omit<
    BatchExportConfiguration,
    'id' | 'destination' | 'start_at' | 'end_at'
> &
    Partial<BatchExportDestinationPostgres['config']> &
    Partial<BatchExportDestinationRedshift['config']> &
    Partial<BatchExportDestinationBigQuery['config']> &
    Partial<BatchExportDestinationS3['config']> &
    Partial<BatchExportDestinationSnowflake['config']> & {
        destination: 'S3' | 'Snowflake' | 'Postgres' | 'BigQuery' | 'Redshift'
        start_at: Dayjs | null
        end_at: Dayjs | null
        json_config_file?: File[] | null
    }

export const batchExportFormFields = (
    isNew: boolean,
    { name, destination, interval, start_at, end_at, paused, ...config }: BatchExportConfigurationForm,
    { isPipeline }: { isPipeline?: boolean } = {}
): Record<string, any> => {
    // Important! All fields that are required must be checked here as it is used also to sanitise the existing

    return {
        name: !name && !isPipeline ? 'Please enter a name' : '', // In pipeline UI the name is in the top bar
        destination: !destination ? 'Please select a destination' : '',
        interval: !interval ? 'Please select a frequency' : '',
        paused: '',
        start_at: '',
        end_at: '',
        ...(destination === 'Postgres'
            ? {
                  user: isNew ? (!config.user ? 'This field is required' : '') : '',
                  password: isNew ? (!config.password ? 'This field is required' : '') : '',
                  host: !config.host ? 'This field is required' : '',
                  port: !config.port ? 'This field is required' : '',
                  database: !config.database ? 'This field is required' : '',
                  schema: !config.schema ? 'This field is required' : '',
                  table_name: !config.table_name ? 'This field is required' : '',
                  has_self_signed_cert: false,
                  exclude_events: '',
                  include_events: '',
              }
            : destination === 'Redshift'
            ? {
                  user: isNew ? (!config.user ? 'This field is required' : '') : '',
                  password: isNew ? (!config.password ? 'This field is required' : '') : '',
                  host: !config.host ? 'This field is required' : '',
                  port: !config.port ? 'This field is required' : '',
                  database: !config.database ? 'This field is required' : '',
                  schema: !config.schema ? 'This field is required' : '',
                  table_name: !config.table_name ? 'This field is required' : '',
                  properties_data_type: '',
                  exclude_events: '',
                  include_events: '',
              }
            : destination === 'S3'
            ? {
                  bucket_name: !config.bucket_name ? 'This field is required' : '',
                  region: !config.region ? 'This field is required' : '',
                  prefix: !config.prefix ? 'This field is required' : '',
                  aws_access_key_id: isNew ? (!config.aws_access_key_id ? 'This field is required' : '') : '',
                  aws_secret_access_key: isNew ? (!config.aws_secret_access_key ? 'This field is required' : '') : '',
                  compression: '',
                  encryption: '',
                  kms_key_id: !config.kms_key_id && config.encryption == 'aws:kms' ? 'This field is required' : '',
                  exclude_events: '',
                  include_events: '',
              }
            : destination === 'BigQuery'
            ? {
                  json_config_file: isNew
                      ? !config.json_config_file
                          ? 'This field is required'
                          : !config.project_id ||
                            !config.private_key ||
                            !config.private_key_id ||
                            !config.client_email ||
                            !config.token_uri
                          ? 'The config file is not valid'
                          : ''
                      : '',
                  dataset_id: !config.dataset_id ? 'This field is required' : '',
                  table_id: !config.table_id ? 'This field is required' : '',
                  exclude_events: '',
                  include_events: '',
                  use_json_type: '',
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
                  exclude_events: '',
                  include_events: '',
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

    forms(({ props, actions }) => ({
        batchExportConfigForm: {
            defaults: {
                name: '',
            } as BatchExportConfigurationForm,
            errors: (form) => batchExportFormFields(props.id === 'new', form),
            submit: async ({ name, destination, interval, start_at, end_at, paused, ...config }) => {
                const destinationObject: BatchExportDestination =
                    destination === 'Postgres'
                        ? ({
                              type: 'Postgres',
                              config: config,
                          } as unknown as BatchExportDestinationPostgres)
                        : destination === 'S3'
                        ? ({
                              type: 'S3',
                              config: config,
                          } as unknown as BatchExportDestinationS3)
                        : destination === 'Redshift'
                        ? ({
                              type: 'Redshift',
                              config: config,
                          } as unknown as BatchExportDestinationRedshift)
                        : destination === 'BigQuery'
                        ? ({
                              type: 'BigQuery',
                              config: config,
                          } as unknown as BatchExportDestinationBigQuery)
                        : ({
                              type: 'Snowflake',
                              config: config,
                          } as unknown as BatchExportDestinationSnowflake)

                const data: Omit<BatchExportConfiguration, 'id' | 'created_at' | 'team_id'> = {
                    paused,
                    name,
                    interval,
                    start_at: start_at?.toISOString() ?? null,
                    end_at: end_at?.toISOString() ?? null,
                    destination: destinationObject,
                }

                const result =
                    props.id === 'new'
                        ? await api.batchExports.create(data)
                        : await api.batchExports.update(props.id, data)

                await new Promise((resolve) => setTimeout(resolve, 1000))

                actions.resetBatchExportConfigForm()
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

        setBatchExportConfigFormValue: async ({ name, value }) => {
            if (name[0] === 'json_config_file' && value) {
                try {
                    const loadedFile: string = await new Promise((resolve, reject) => {
                        const filereader = new FileReader()
                        filereader.onload = (e) => resolve(e.target?.result as string)
                        filereader.onerror = (e) => reject(e)
                        filereader.readAsText(value[0])
                    })
                    const jsonConfig = JSON.parse(loadedFile)
                    actions.setBatchExportConfigFormValues({
                        ...values.batchExportConfigForm,
                        project_id: jsonConfig.project_id,
                        private_key: jsonConfig.private_key,
                        private_key_id: jsonConfig.private_key_id,
                        client_email: jsonConfig.client_email,
                        token_uri: jsonConfig.token_uri,
                    })
                } catch (e) {
                    actions.setBatchExportConfigFormManualErrors({
                        json_config_file: 'The config file is not valid',
                    })
                }
            }
        },

        loadBatchExportConfigSuccess: ({ batchExportConfig }) => {
            if (!batchExportConfig) {
                return
            }

            const destination = batchExportConfig.destination.type

            const transformedConfig: BatchExportConfigurationForm = {
                ...batchExportConfig,
                destination,
                start_at: batchExportConfig.start_at ? dayjs(batchExportConfig.start_at) : null,
                end_at: batchExportConfig.end_at ? dayjs(batchExportConfig.end_at) : null,
                ...batchExportConfig.destination.config,
            }

            // Filter out any values that aren't part of our from

            const validFormFields = Object.keys(batchExportFormFields(props.id === 'new', transformedConfig))

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
                    key: Scene.BatchExports,
                    name: 'Batch Exports',
                    path: urls.batchExports(),
                },
                ...(isNew
                    ? [
                          {
                              key: 'new',
                              name: 'New',
                          },
                      ]
                    : [
                          {
                              key: config?.id ?? 'loading',
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
