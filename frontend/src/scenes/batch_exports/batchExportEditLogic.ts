import { actions, afterMount, kea, key, listeners, path, props, selectors } from 'kea'

import { loaders } from 'kea-loaders'
import {
    BatchExportConfiguration,
    BatchExportDestination,
    BatchExportDestinationS3,
    BatchExportDestinationSnowflake,
} from '~/types'

import api from 'lib/api'
import { forms } from 'kea-forms'
import { urls } from 'scenes/urls'
import { beforeUnload, router } from 'kea-router'

import type { batchExportsEditLogicType } from './batchExportEditLogicType'
import { dayjs, Dayjs } from 'lib/dayjs'
import { subscriptions } from 'kea-subscriptions'

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

const formFields = ({
    name,
    destination,
    interval,
    start_at,
    end_at,
    ...config
}: BatchExportConfigurationFrom): Record<string, any> => {
    // Important! All fields that are required must be checked here as it is used also to sanitise the existing
    return {
        name: !name ? 'Please enter a name' : '',
        destination: !destination ? 'Please select a destination' : '',
        interval: !interval ? 'Please select a frequency' : '',
        start_at: '',
        end_at: '',
        ...(destination === 'S3'
            ? {
                  bucket_name: !config.bucket_name ? 'This field is required' : '',
                  region: !config.region ? 'This field is required' : '',
                  prefix: !config.prefix ? 'This field is required' : '',
                  aws_access_key_id: !config.aws_access_key_id ? 'This field is required' : '',
                  aws_secret_access_key: !config.aws_secret_access_key ? 'This field is required' : '',
              }
            : destination === 'Snowflake'
            ? {
                  account: !config.account ? 'This field is required' : '',
                  database: !config.database ? 'This field is required' : '',
                  warehouse: !config.warehouse ? 'This field is required' : '',
                  user: !config.user ? 'This field is required' : '',
                  password: !config.password ? 'This field is required' : '',
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
    actions({
        cancelEditing: true,
    }),

    loaders(({ props }) => ({
        existingBatchExportConfig: [
            null as BatchExportConfiguration | null,
            {
                loadBatchExportConfig: async () => {
                    if (props.id === 'new') {
                        return null
                    }
                    const res = await api.batchExports.get(props.id)
                    return res
                },
            },
        ],
    })),

    forms(({ props }) => ({
        batchExportConfig: {
            defaults: {
                name: '',
            } as BatchExportConfigurationFrom,
            errors: (form) => formFields(form),
            submit: async ({ name, destination, interval, start_at, end_at, ...config }) => {
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

                const data: Omit<BatchExportConfiguration, 'id'> = {
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

        loadBatchExportConfigSuccess: ({ existingBatchExportConfig }) => {
            if (!existingBatchExportConfig) {
                return
            }
            const destination = existingBatchExportConfig.destination.type

            const transformedConfig: BatchExportConfigurationFrom = {
                ...existingBatchExportConfig,
                destination,
                start_at: existingBatchExportConfig.start_at ? dayjs(existingBatchExportConfig.start_at) : null,
                end_at: existingBatchExportConfig.end_at ? dayjs(existingBatchExportConfig.end_at) : null,
                ...existingBatchExportConfig.destination.config,
            }

            // Filter out any values that aren't part of our from

            const validFormFields = Object.keys(formFields(transformedConfig))

            Object.keys(transformedConfig).forEach((key) => {
                if (!validFormFields.includes(key)) {
                    delete transformedConfig[key]
                }
            })

            actions.setBatchExportConfigValues(transformedConfig)
        },
    })),

    subscriptions(({ path, values }) => ({
        batchExportConfig: (config) => {
            const copiedConfig = { ...config }

            // NOTE: Do we want to store things...
            if (values.batchExportConfigChanged) {
                sessionStorage.setItem([...path, 'cachedForm'].join('.'), JSON.stringify(copiedConfig))
            }
        },
    })),

    selectors({
        isNew: [() => [(_, props) => props], (props): boolean => props.id === 'new'],
    }),

    afterMount(({ values, path, actions }) => {
        if (values.isNew) {
            try {
                const cachedConfig = JSON.parse(sessionStorage.getItem([...path, 'cachedForm'].join('.')) ?? '')
                actions.setBatchExportConfigValues(cachedConfig)
            } catch (e) {}
        } else {
            actions.loadBatchExportConfig()
        }
    }),

    beforeUnload(({ values }) => ({
        enabled: () => values.batchExportConfigChanged,
        message: `Leave?\nChanges you made will be discarded.`,
    })),
])
