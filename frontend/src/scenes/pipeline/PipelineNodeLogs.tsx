import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSnack, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LOGS_PORTION_LIMIT } from 'lib/constants'
import { pluralize } from 'lib/utils'

import { PipelineNodeLogicProps } from './pipelineNodeLogic'
import { ALL_LOG_LEVELS, pipelineNodeLogsLogic } from './pipelineNodeLogsLogic'

export function PipelineNodeLogs({ id, stage }: PipelineNodeLogicProps): JSX.Element {
    const logic = pipelineNodeLogsLogic({ id, stage })

    const { logs, logsLoading, backgroundLogs, columns, isThereMoreToLoad, selectedLogLevels, instanceId } =
        useValues(logic)
    const { revealBackground, loadMoreLogs, setSelectedLogLevels, setSearchTerm, setInstanceId } = useActions(logic)

    return (
        <div className="flex-1 ph-no-capture deprecated-space-y-2">
            <LemonInput
                type="search"
                placeholder="Search for messages containing…"
                fullWidth
                onChange={setSearchTerm}
                allowClear
                prefix={
                    <>
                        <IconSearch />

                        {instanceId && <LemonSnack onClose={() => setInstanceId(null)}>{instanceId}</LemonSnack>}
                    </>
                }
            />
            <div className="flex gap-4 items-center">
                <span className="mr-1">Show logs of level:</span>
                {ALL_LOG_LEVELS.map((level) => {
                    return (
                        <LemonCheckbox
                            key={level}
                            label={level}
                            checked={selectedLogLevels.includes(level)}
                            onChange={(checked) => {
                                const newLogLevels = checked
                                    ? [...selectedLogLevels, level]
                                    : selectedLogLevels.filter((t) => t != level)
                                setSelectedLogLevels(newLogLevels)
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
                disabledReason={!backgroundLogs.length ? "There's nothing to load" : undefined}
            >
                {backgroundLogs.length
                    ? `Load ${pluralize(backgroundLogs.length, 'newer entry', 'newer entries')}`
                    : 'No new entries'}
            </LemonButton>

            <LemonTable
                dataSource={logs}
                columns={columns}
                loading={logsLoading}
                className="ph-no-capture"
                rowKey={(record) => `${record.log_source_id}:${record.instance_id}:${record.timestamp}`}
                pagination={{ pageSize: 200, hideOnSinglePage: true }}
            />
            {!!logs.length && (
                <LemonButton
                    onClick={loadMoreLogs}
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
