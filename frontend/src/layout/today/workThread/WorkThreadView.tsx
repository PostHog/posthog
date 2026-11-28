import { Callout, CalloutContent, CalloutDescription, CalloutTitle, Text } from '@posthog/quill'

import type { WorkStepApi, WorkThreadApi } from 'products/today/frontend/generated/api.schemas'

import { WorkThreadItemDrawer } from './WorkThreadItemDrawer'
import { WorkThreadLine } from './WorkThreadLine'
import { workThreadSummary } from './workThreadState'
import type { WorkRunActionHandler } from './workThreadTypes'

interface WorkThreadViewProps {
    thread: WorkThreadApi
    renderEvidence?: (step: WorkStepApi) => JSX.Element | null
    onRunAction: WorkRunActionHandler
}

function counted(count: number, one: string, many: string): string {
    return `${count} ${count === 1 ? one : many}`
}

export function WorkThreadView({ thread, renderEvidence, onRunAction }: WorkThreadViewProps): JSX.Element {
    const summary = workThreadSummary(thread)
    const counts = [
        counted(summary.inOrder, 'step in order', 'steps in order'),
        `${summary.alongside} alongside`,
        counted(summary.needsYou, 'needs you', 'need you'),
    ].join(' · ')

    return (
        <div data-quill className="@container/work-thread flex min-w-0 flex-col gap-4" data-attr="work-thread">
            <Text size="xs" variant="muted" className="m-0" data-attr="work-thread-summary">
                {counts}
            </Text>
            <WorkThreadLine
                thread={thread}
                line={thread.line}
                renderEvidence={renderEvidence}
                onRunAction={onRunAction}
            />
            {summary.needsYou === 0 && (
                <Callout tone={summary.waiting > 0 ? 'default' : 'success'} data-attr="work-thread-closing">
                    <CalloutContent>
                        <CalloutTitle>
                            {summary.waiting > 0 ? 'Nothing needs you right now' : 'This thread is finished'}
                        </CalloutTitle>
                        <CalloutDescription>
                            {summary.waiting > 0
                                ? 'Each waiting step says what has to happen before it can start.'
                                : 'Every step is done.'}
                        </CalloutDescription>
                    </CalloutContent>
                </Callout>
            )}
            <WorkThreadItemDrawer thread={thread} renderEvidence={renderEvidence} />
        </div>
    )
}
