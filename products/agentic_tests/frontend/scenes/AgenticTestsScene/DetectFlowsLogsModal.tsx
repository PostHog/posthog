import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { TaskSessionView } from 'products/tasks/frontend/components/TaskSessionView'

import { detectFlowsLogic } from './detectFlowsLogic'

export function DetectFlowsLogsModal(): JSX.Element {
    const { logsModalOpen, streamEntries, isStreaming, isTerminal } = useValues(detectFlowsLogic)
    const { closeLogsModal } = useActions(detectFlowsLogic)

    return (
        <LemonModal
            isOpen={logsModalOpen}
            onClose={closeLogsModal}
            title={isTerminal ? 'Flow detection complete' : 'Auto-detecting flows...'}
            width="80%"
            maxWidth={960}
        >
            <div className="max-h-[60vh] overflow-auto">
                <TaskSessionView
                    logs=""
                    streamEntries={streamEntries}
                    isPolling={!isStreaming && !isTerminal}
                    isStreaming={isStreaming}
                    run={null}
                />
            </div>
        </LemonModal>
    )
}
