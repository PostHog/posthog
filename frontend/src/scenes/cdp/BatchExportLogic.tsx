import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import {
    BatchExportDestinationType,
    S3BatchExportConfigType,
    BatchExportTabsType,
    ChangeExportRunStatusEnum,
    ConnectionChoiceType,
    BatchExportRunType,
    CreateBatchExportScheduleType as CreateOrUpdateBatchExportScheduleType,
    S3ConfigType,
    BatchExportFrequencyType as BatchExportFrequencyEnum,
} from './types'
import { mockConnectionChoices, mockExportRuns } from './mocks'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import { teamLogic } from 'scenes/teamLogic'
import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'

import { urls } from 'scenes/urls'
import { Breadcrumb } from '~/types'

import type { BatchExportLogicType } from './BatchExportLogicType'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from '@posthog/lemon-ui'
import { SECRET_FIELD_VALUE } from 'scenes/plugins/utils'

interface BatchExportLogicProps {
    id: string
}

const defaultCreator = (values: BatchExportLogicType['values']): S3BatchExportConfigType => ({
    name: values.connectionChoice?.name || 'New connection',
    schedule: {
        frequency: BatchExportFrequencyEnum.TwelveHours,
        firstExport: dayjsUtcToTimezone(new Date().toISOString(), values.timezone).add(1, 'day').startOf('day') as any,
        stopAtSpecificDate: false,
        stopAt: undefined,
        backfillRecords: false,
        backfillFrom: undefined,
    },
    config: {
        AWSAccessKeyID: '' as string,
        AWSSecretAccessKey: '' as string,
        AWSRegion: '' as string,
        AWSBucket: '' as string,
        fileFormat: 'csv' as any,
        fileName: DEFAULT_FILE_NAME as any,
    },
})

const settingsValidation = (values: S3BatchExportConfigType): Record<string, any> => {
    return {
        name: values.name ? undefined : 'Name is required',
        config: {
            AWSAccessKeyID: values.config.AWSAccessKeyID ? undefined : 'AWS Access Key ID is required',
            AWSSecretAccessKey: values.config.AWSSecretAccessKey ? undefined : 'AWS Secret Access Key is required',
            AWSRegion: values.config.AWSRegion ? undefined : 'AWS Region is required',
            AWSBucket: values.config.AWSBucket ? undefined : 'AWS Bucket is required',
            fileFormat: values.config.fileFormat ? undefined : 'File format is required',
            fileName: values.config.fileName ? undefined : 'File name is required',
        },
    }
}

export const DEFAULT_FILE_NAME = 'posthog-events/{year}/{month}/{day}/{hour}:{minute}:{second}/{partitionId}.csv'

export const BatchExportLogic = kea<BatchExportLogicType>([
    path(['scenes', 'cdp', 'BatchExportLogic']),
    connect({
        values: [teamLogic, ['timezone']],
    }),
    props({} as BatchExportLogicProps),
    key((props) => props.id ?? 'new'),
    actions({
        setTab: (tab: BatchExportTabsType) => ({ tab }),
        setEditingSecret: (editingSecret: boolean) => ({ editingSecret }),
    }),
    reducers({
        connectionChoices: [mockConnectionChoices as ConnectionChoiceType[], {}],
        activeTab: [
            'sync-history' as BatchExportTabsType,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
        editingSecret: [
            true as boolean,
            {
                setEditingSecret: (_, { editingSecret }) => editingSecret,
            },
        ],
    }),
    loaders(({ props }) => ({
        connectionChoices: [
            undefined as ConnectionChoiceType[] | undefined,
            {
                loadConnectionChoices: async () => {
                    const connectionChoices = await Promise.resolve(mockConnectionChoices)
                    return connectionChoices
                },
            },
        ],
        batchExportDestination: [
            undefined as BatchExportDestinationType | undefined,
            {
                loadBatchExportDestination: async () => {
                    const batchExport = props.id ? await api.batchExports.exports.get(props.id) : undefined
                    return batchExport
                },
            },
        ],
        exportRuns: [
            [] as BatchExportRunType[],
            {
                loadExportRuns: async () => {
                    const exportRuns = await Promise.resolve(mockExportRuns)
                    return exportRuns
                },
                changeExportRunStatus: async ({ id, action }: { id: string; action: ChangeExportRunStatusEnum }) => {
                    console.log('changeExportRunStatus', id, action)
                    const exportRuns = await Promise.resolve(mockExportRuns)
                    return exportRuns
                },
            },
        ],
    })),
    forms(({ values, props }) => ({
        batchExportSettings: {
            defaults: defaultCreator(values),
            errors: settingsValidation,
            submit: async (values: S3BatchExportConfigType) => {
                console.log('submitting', values)

                const name = values.name
                const type = 'S3' // TODO: make this real
                const primary_schedule: CreateOrUpdateBatchExportScheduleType['primary_schedule'] = {
                    start_at: values.schedule.firstExport.toISOString(),
                    end_at: values.schedule.stopAtSpecificDate ? values.schedule.stopAt?.toISOString() : undefined,
                    intervals: [
                        {
                            every: values.schedule.frequency,
                            offset: 0, // TODO: add in the real offset
                        },
                    ], // TODO: work out what to do here
                }

                const config: Partial<S3ConfigType> = {
                    AWSAccessKeyID: values.config.AWSAccessKeyID,
                    AWSSecretAccessKey: values.config.AWSSecretAccessKey,
                    AWSRegion: values.config.AWSRegion,
                    AWSBucket: values.config.AWSBucket,
                    fileFormat: values.config.fileFormat,
                    fileName: values.config.fileName,
                }

                // SECRET_FIELD_VALUE is a special value that means "don't change this field"
                if (config.AWSSecretAccessKey === SECRET_FIELD_VALUE) {
                    delete config['AWSSecretAccessKey']
                }

                const createBatchExport: CreateOrUpdateBatchExportScheduleType = {
                    name,
                    type,
                    primary_schedule,
                    config,
                }

                console.log('createBatchExportSchedule', createBatchExport)

                if (props.id) {
                    await api.batchExports.exports.update(props.id, createBatchExport)
                    lemonToast.success('Export saved')
                    return
                } else {
                    const result = await api.batchExports.exports.create(createBatchExport)
                    lemonToast.success('Export saved')
                    console.log(result)
                }

                // TODO: don't send the placeholder AWSSecretAccessKey unless it's been changed
                // TODO: turn off seconds in the date pickers
            },
        },
    })),
    selectors({
        connectionChoice: [
            (s) => [s.connectionChoices, (_, props) => props.id],
            (connectionChoices, connectionChoiceId): ConnectionChoiceType | undefined => {
                return connectionChoices?.find((connectionChoice) => connectionChoice.id === connectionChoiceId)
            },
        ],
        fileNamePreview: [
            (s) => [s.batchExportSettings],
            (batchExportSettings) => {
                const now = dayjs()
                const partitionId = '345345'

                const date_components = [
                    ['year', 'YYYY'],
                    ['month', 'MM'],
                    ['day', 'DD'],
                    ['hour', 'HH'],
                    ['minute', 'mm'],
                    ['second', 'ss'],
                ]

                let fileNamePreview = batchExportSettings.config.fileName

                date_components.forEach(([component, format]) => {
                    fileNamePreview = fileNamePreview?.replace(`{${component}}`, now.format(format))
                })

                fileNamePreview = fileNamePreview?.replace('{partitionId}', partitionId)
                return fileNamePreview
            },
        ],
        breadcrumbs: [
            (s) => [s.batchExportSettings],
            (batchExportDestination: BatchExportDestinationType): Breadcrumb[] => [
                {
                    name: 'CDP',
                    path: urls.cdp(),
                },
                {
                    name: batchExportDestination.name,
                    path: urls.cdpBatchExport(batchExportDestination.id),
                },
            ],
        ],
    }),
    listeners(({ actions, values }) => ({
        loadConnectionChoicesSuccess: () => {
            actions.setBatchExportSettingsValues({
                name: values.batchExportSettings.name || values?.connectionChoice?.name,
            })
        },
        loadConnectionSettingsSuccess: ({ connectionSettings }) => {
            actions.setEditingSecret(!connectionSettings?.AWSSecretAccessKey)
        },
        loadBatchExportDestinationSuccess: ({ batchExportDestination }) => {
            console.log(batchExportDestination)
            actions.setBatchExportSettingsValues({
                name: batchExportDestination.name,
                schedule: {
                    firstExport: dayjs(batchExportDestination.primary_schedule.start_at),
                    stopAt: dayjs(batchExportDestination.primary_schedule.end_at),
                    frequency: batchExportDestination.primary_schedule.intervals[0].every,
                },
                config: batchExportDestination.config,
            })
        },
    })),
    afterMount(({ actions }) => {
        console.log('after mount')
        actions.loadConnectionChoices()
        actions.loadBatchExportDestination()
        actions.loadExportRuns()
    }),
    urlToAction(({ actions }) => ({
        [urls.featureFlags()]: async (_, searchParams) => {
            const choiceId = searchParams['choiceId']
            if (choiceId) {
                actions.setConnectionChoice(choiceId)
            }
        },
    })),
])
