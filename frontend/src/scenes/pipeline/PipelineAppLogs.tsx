import { LemonButton, LemonCheckbox, LemonInput, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LOGS_PORTION_LIMIT } from 'lib/constants'
import { pluralize } from 'lib/utils'

import { PipelineAppLogLevel, pipelineAppLogsLogic, PipelineAppLogsProps } from './pipelineAppLogsLogic'

export function PipelineAppLogs({ id, kind }: PipelineAppLogsProps): JSX.Element {
    const logic = pipelineAppLogsLogic({ id, kind })

    const { logs, logsLoading, pluginLogsBackground, columns, isThereMoreToLoad, selectedLogLevels } = useValues(logic)
    const { revealBackground, loadPluginLogsMore, setSelectedLogLevels, setSearchTerm } = useActions(logic)

    return (
        <div className="ph-no-capture space-y-2 flex-1">
            <LemonInput
                type="search"
                placeholder="Search for messages containing…"
                fullWidth
                onChange={setSearchTerm}
                allowClear
            />
            <div className="flex items-center gap-4">
                <span className="mr-1">Show logs of level:</span>
                {Object.values(PipelineAppLogLevel).map((level) => {
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
                disabledReason={!pluginLogsBackground.length ? "There's nothing to load" : undefined}
            >
                {pluginLogsBackground.length
                    ? `Load ${pluralize(pluginLogsBackground.length, 'newer entry', 'newer entries')}`
                    : 'No new entries'}
            </LemonButton>

            <LemonTable
                dataSource={logs}
                columns={columns}
                loading={logsLoading}
                size="small"
                className="ph-no-capture"
                rowKey="id"
                pagination={{ pageSize: 200, hideOnSinglePage: true }}
            />
            {!!logs.length && (
                <LemonButton
                    onClick={loadPluginLogsMore}
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
