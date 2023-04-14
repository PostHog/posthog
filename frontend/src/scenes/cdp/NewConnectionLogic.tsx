import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { NewConnectionLogicType } from './NewConnectionLogicType'
import { BatchExportSettingsType, ConnectionChoiceType } from './types'
import { mockConnectionChoices } from './mocks'
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
    }),
    reducers({
        connectionChoices: [mockConnectionChoices as ConnectionChoiceType[], {}],
        activeTab: [
            'settings' as BatchExportTabsType,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
    loaders({
        connectionChoices: [
            undefined as ConnectionChoiceType[] | undefined,
            {
                loadConnectionChoice: async () => {
                    const connectionChoices = await Promise.resolve(mockConnectionChoices)
                    return connectionChoices
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
                    fileNamePreview = fileNamePreview.replace(`{${component}}`, now.format(format))
                })

                fileNamePreview = fileNamePreview.replace('{partitionId}', partitionId)

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
    afterMount(({ actions }) => {
        actions.loadConnectionChoice()
    }),
    listeners(({ actions, values }) => ({
        loadConnectionChoiceSuccess: () => {
            actions.setConnectionSettingsValues({
                name: values.connectionSettings.name || values?.connectionChoice?.name,
            })
        },
    })),
])
