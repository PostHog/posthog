import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { NewConnectionLogicType } from './NewConnectionLogicType'
import {
    BatchExportConnectionType,
    BatchExportSettingsType,
    BatchExportTabsType,
    ChangeExportRunStatusEnum,
    ConnectionChoiceType,
    ExportRunType,
} from './types'
import { mockConnectionChoices, mockExportRuns } from './mocks'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import { teamLogic } from 'scenes/teamLogic'
import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'

import { urls } from 'scenes/urls'
import { Breadcrumb } from '~/types'

interface NewConnectionLogicProps {
    id: string
}

const defaultCreator = (values: NewConnectionLogicType['values']): BatchExportSettingsType => ({
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

export const NewConnectionLogic = kea<NewConnectionLogicType>([
    path(['scenes', 'cdp', 'NewConnectionLogic']),
    connect({
        values: [teamLogic, ['timezone']],
    }),
    props({} as NewConnectionLogicProps),
    key((props) => props.id ?? 'default'),
    actions({
        setTab: (tab: BatchExportTabsType) => ({ tab }),
        setEditingSecret: (editingSecret: boolean) => ({ editingSecret }),
    }),
    reducers({
        connection: [
            {
                id: '123',
                name: 'Test Connection',
                status: 'active',
                connection_type_id: 's3',
                successRate: '100%',
                imageUrl: 'https://posthog.com/static/brand/favicon.png',
                settings: {},
            } as BatchExportConnectionType,
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
        connectionSettings: [
            undefined as BatchExportSettingsType | undefined,
            {
                loadConnectionSettings: async () => {
                    const connectionSettings = await Promise.resolve(undefined)
                    return connectionSettings
                },
            },
        ],
        exportRuns: [
            [] as ExportRunType[] | undefined,
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
        connectionSettings: {
            defaults: defaultCreator(values),
            validate: (values: BatchExportSettingsType) => {
                return {
                    name: values.name ? undefined : 'Name is required',
                }
            },
            submit: async (values: BatchExportSettingsType) => {
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
            (s) => [s.connectionSettings],
            (connectionSettings) => {
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

                let fileNamePreview = connectionSettings.fileName

                date_components.forEach(([component, format]) => {
                    fileNamePreview = fileNamePreview?.replace(`{${component}}`, now.format(format))
                })

                fileNamePreview = fileNamePreview?.replace('{partitionId}', partitionId)
                return fileNamePreview
            },
        ],
        breadcrumbs: [
            (s) => [s.connectionChoice],
            (): Breadcrumb[] => [
                {
                    name: 'CDP',
                    path: urls.cdp(),
                },
                // ...(featureFlag ? [{ name: featureFlag.key || 'Unnamed' }] : []),
            ],
        ],
    }),
    listeners(({ actions, values }) => ({
        loadConnectionChoicesSuccess: () => {
            actions.setConnectionSettingsValues({
                name: values.connectionSettings.name || values?.connectionChoice?.name,
            })
        },
        loadConnectionSettingsSuccess: ({ connectionSettings }) => {
            actions.setEditingSecret(!connectionSettings?.AWSSecretAccessKey)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadConnectionChoices()
        actions.loadExportRuns()
        actions.loadConnectionSettings()
    }),
])
