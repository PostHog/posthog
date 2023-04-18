import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import {
    BatchExportDestinationType,
    S3BatchExportConfigType,
    BatchExportTabsType,
    ChangeExportRunStatusEnum,
    ConnectionChoiceType,
    BatchExportRunType,
} from './types'
import { mockConnectionChoices, mockExportRuns } from './mocks'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import { teamLogic } from 'scenes/teamLogic'
import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'

import { urls } from 'scenes/urls'
import { Breadcrumb } from '~/types'

import type { BatchExportLogicType } from './BatchExportLogicType'

interface BatchExportLogicProps {
    id: string
}

const defaultCreator = (values: BatchExportLogicType['values']): S3BatchExportConfigType => ({
    name: '',
    frequency: '12',
    firstExport: dayjsUtcToTimezone(new Date().toISOString(), values.timezone).add(1, 'day').startOf('day') as any,
    stopAtSpecificDate: false,
    stopAt: undefined,
    backfillRecords: false,
    backfillFrom: undefined,
    AWSAccessKeyID: '' as string,
    AWSSecretAccessKey: '' as string,
    AWSRegion: '' as string,
    AWSBucket: '' as string,
    fileFormat: 'csv' as any,
    fileName: DEFAULT_FILE_NAME as any,
})

export const DEFAULT_FILE_NAME = 'posthog-events/{year}/{month}/{day}/{hour}:{minute}:{second}/{partitionId}.csv'

export const BatchExportLogic = kea<BatchExportLogicType>([
    path(['scenes', 'cdp', 'BatchExportLogic']),
    connect({
        values: [teamLogic, ['timezone']],
    }),
    props({} as BatchExportLogicProps),
    key((props) => props.id ?? 'default'),
    actions({
        setTab: (tab: BatchExportTabsType) => ({ tab }),
        setEditingSecret: (editingSecret: boolean) => ({ editingSecret }),
    }),
    reducers({
        batchExportDestination: [
            {
                id: '123',
                name: 'Test Batch Export Destination',
                status: 'active',
                connection_type_id: 's3',
                successRate: '100%',
                imageUrl: 'https://posthog.com/static/brand/favicon.png',
                config: {},
            } as BatchExportDestinationType,
            {},
        ],
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
    loaders({
        connectionChoices: [
            undefined as ConnectionChoiceType[] | undefined,
            {
                loadConnectionChoices: async () => {
                    const connectionChoices = await Promise.resolve(mockConnectionChoices)
                    return connectionChoices
                },
            },
        ],
        batchExportSettings: [
            undefined as S3BatchExportConfigType | undefined,
            {
                loadBatchExportSettings: async () => {
                    const batchExportSettings = await Promise.resolve(undefined)
                    return batchExportSettings
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
    }),
    forms(({ values }) => ({
        batchExportSettings: {
            defaults: defaultCreator(values),
            validate: (values: S3BatchExportConfigType) => {
                return {
                    name: values.name ? undefined : 'Name is required',
                }
            },
            submit: async (values: S3BatchExportConfigType) => {
                console.log('submitting', values)
                // TODO: don't send the placeholder AWSSecretAccessKey unless it's been changed
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

                let fileNamePreview = batchExportSettings.fileName

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
    })),
    afterMount(({ actions }) => {
        actions.loadConnectionChoices()
        actions.loadExportRuns()
        actions.loadBatchExportSettings()
    }),
])
