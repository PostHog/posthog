import { afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { NewConnectionLogicType } from './NewConnectionLogicType'
import { BatchExportSettings, ConnectionChoiceType } from './types'
import { mockConnectionChoices } from './mocks'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import { teamLogic } from 'scenes/teamLogic'
import { dayjs, dayjsUtcToTimezone } from 'lib/dayjs'

interface NewConnectionLogicProps {
    id: string
}

export const NewConnectionLogic = kea<NewConnectionLogicType>([
    path(['scenes', 'cdp', 'NewConnectionLogic']),
    connect({
        values: [teamLogic, ['timezone']],
    }),
    props({} as NewConnectionLogicProps),
    key((props) => props.id ?? 'default'),
    reducers({
        connectionChoices: [mockConnectionChoices as ConnectionChoiceType[], {}],
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
            defaults: {
                frequency: '12' as BatchExportSettings['frequency'],
                firstExport: dayjsUtcToTimezone(new Date().toISOString(), values.timezone).add(1, 'day').startOf('day'),
                sourceTable: 'events',
                fileFormat: 'csv',
                runUntil: 'forever',
                fileName: 'posthog-events/{year}/{month}/{day}/{hour}:{minute}:{second}/{partitionId}.csv',
                // backfillFrom: dayjsUtcToTimezone(0, values.timezone),
            },
            validate: (values: BatchExportSettings) => {
                return {
                    // TODO: update these
                    name: values.name ? undefined : 'Name is required',
                    frequency: values.frequency ? undefined : 'Frequency is required',
                    startAt: values.startAt ? undefined : 'Start at is required',
                    sourceTable: values.sourceTable ? undefined : 'Source table is required',
                    AWSAccessKeyID: values.AWSAccessKeyID ? undefined : 'AWS Access Key ID is required',
                    AWSSecretAccessKey: values.AWSSecretAccessKey ? undefined : 'AWS Secret Access Key is required',
                    AWSRegion: values.AWSRegion ? undefined : 'AWS Region is required',
                    AWSBucket: values.AWSBucket ? undefined : 'AWS Bucket is required',
                    fileFormat: values.fileFormat ? undefined : 'File format is required',
                }
            },
        },
    })),
    selectors({
        connectionChoice: [
            (s) => [s.connectionChoices, (_, props) => props.id],
            (connectionChoices, connectionChoiceId): ConnectionChoiceType | undefined => {
                return connectionChoices.find((connectionChoice) => connectionChoice.id === connectionChoiceId)
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
    }),
    afterMount(({ actions }) => {
        actions.loadConnectionChoice()
    }),
    listeners(({ actions, values }) => ({
        loadConnectionChoiceSuccess: () => {
            actions.setConnectionSettingsValues({
                name: values.connectionSettings.name ?? values.connectionChoice.name,
            })
        },
    })),
    // selectors({
    //     connectionChoice: [
    //         (s) => [s.connectionChoices],
    //         (connectionChoices, connectionChoiceId): ConnectionChoiceType | undefined => {
    //             debugger
    //             return connectionChoices.find((connectionChoice) => connectionChoice.id === connectionChoiceId)
    //         },
    //     ],
    // }),
])
