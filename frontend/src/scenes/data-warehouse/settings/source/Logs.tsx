import {
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTableColumns,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LOGS_PORTION_LIMIT } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils'
import { LogLevelDisplay } from 'scenes/pipeline/utils'

import { ExternalDataSourceSchema, LogEntry } from '~/types'

import {
    dataWarehouseSourceSettingsLogic,
    DataWarehouseSourceSettingsLogicProps,
} from './dataWarehouseSourceSettingsLogic'
import { ALL_LOG_LEVELS, schemaLogLogic } from './schemaLogLogic'

const columns: LemonTableColumns<LogEntry> = [
    {
        title: 'Timestamp',
        key: 'timestamp',
        dataIndex: 'timestamp',
        width: 1,
        render: (_, entry) => dayjs(entry.timestamp).format('YYYY-MM-DD HH:mm:ss.SSS UTC'),
    },
    {
        title: 'Level',
        key: 'level',
        dataIndex: 'level',
        width: 1,
        render: (_, entry) => LogLevelDisplay(entry.level),
    },
    {
        title: 'Run ID',
        key: 'run_id',
        dataIndex: 'instance_id',
        width: 1,
        render: (_, entry) => entry.instance_id,
    },
    {
        title: 'Message',
        key: 'message',
        dataIndex: 'message',
        width: 6,
    },
]

export const Logs = (): JSX.Element => {
    const { source, sourceLoading, parentSettingsTab } = useValues(dataWarehouseSourceSettingsLogic)

    if (sourceLoading && !source) {
        return <LemonSkeleton active />
    }

    return (
        <>
            <LogsView
                settingsLogicProps={{
                    id: source!.id,
                    parentSettingsTab,
                }}
            />
        </>
    )
}

interface LogsTableProps {
    settingsLogicProps: DataWarehouseSourceSettingsLogicProps
}

export const LogsView = ({ settingsLogicProps }: LogsTableProps): JSX.Element => {
    const logic = schemaLogLogic({ settingsLogicProps })
    const { logs, logsLoading, logsBackground, isThereMoreToLoad, levelFilters, source, selectedSchemaId } =
        useValues(logic)
    const { revealBackground, loadSchemaLogsMore, setLogLevelFilters, setSearchTerm, setSchema } = useActions(logic)

    return (
        <div className="ph-no-capture space-y-2 flex-1">
            <h3>Schema</h3>
            <LemonSelect
                placeholder="Select schema"
                value={source!.schemas.find((schema) => schema.id === selectedSchemaId)?.name}
                options={source!.schemas.map((schema) => ({ label: schema.name, value: schema.id }))}
                onChange={(schemaId: ExternalDataSourceSchema['id']) => setSchema(schemaId)}
            />
            <LemonInput
                type="search"
                placeholder="Search for messages containing…"
                fullWidth
                onChange={setSearchTerm}
                allowClear
            />
            <div className="flex items-center gap-4">
                <span>Show logs of type:&nbsp;</span>

                {ALL_LOG_LEVELS.map((type) => {
                    return (
                        <LemonCheckbox
                            key={type}
                            label={type}
                            checked={levelFilters.includes(type)}
                            onChange={(checked) => {
                                const newLogsTypes = checked
                                    ? [...levelFilters, type]
                                    : levelFilters.filter((t) => t != type)
                                setLogLevelFilters(newLogsTypes)
                            }}
                        />
                    )
                })}
            </div>
            <LemonButton
                onClick={revealBackground}
                loading={logsLoading}
                type="secondary"
                fullWidth
                center
                disabledReason={!logsBackground.length ? "There's nothing to load" : undefined}
            >
                {logsBackground.length
                    ? `Load ${pluralize(logsBackground.length, 'newer entry', 'newer entries')}`
                    : 'No new entries'}
            </LemonButton>
            <LemonTable
                dataSource={logs}
                columns={columns}
                loading={logsLoading}
                className="ph-no-capture"
                pagination={{ pageSize: 200, hideOnSinglePage: true }}
            />
            {!!logs.length && (
                <LemonButton
                    onClick={loadSchemaLogsMore}
                    loading={logsLoading}
                    type="secondary"
                    fullWidth
                    center
                    disabledReason={!isThereMoreToLoad ? "There's nothing more to load" : undefined}
                >
                    {isThereMoreToLoad ? `Load up to ${LOGS_PORTION_LIMIT} older entries` : 'No older entries'}
                </LemonButton>
            )}
        </div>
    )
}
