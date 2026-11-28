import { useActions } from 'kea'

import { Button, Text } from '@posthog/quill'

import type { WorkStepApi, WorkThreadApi } from 'products/today/frontend/generated/api.schemas'

import { captureWorkItemViewed } from './workThreadEvents'
import { WorkThreadFacts } from './WorkThreadFacts'
import { workThreadLogic } from './workThreadLogic'

interface WorkThreadEvidenceProps {
    thread: WorkThreadApi
    step: WorkStepApi
    renderEvidence?: (step: WorkStepApi) => JSX.Element | null
}

export function WorkThreadEvidence({ thread, step, renderEvidence }: WorkThreadEvidenceProps): JSX.Element | null {
    const { viewItem } = useActions(workThreadLogic({ threadKey: thread.key }))
    const card = renderEvidence?.(step) ?? null
    const { item, facts } = step

    if (!item && !card && facts.length === 0) {
        return null
    }

    return (
        <section className="flex flex-col gap-2" data-attr="work-thread-evidence">
            <Text size="xs" weight="medium" className="m-0">
                Evidence
            </Text>
            <div className="flex min-w-0 flex-col gap-3 rounded-md border border-dashed border-border p-3">
                {item && (
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <Text size="xxs" variant="muted" className="m-0 min-w-0 font-mono">
                            {`Card supplied by ${item.product}`}
                        </Text>
                        <Button
                            variant="outline"
                            size="sm"
                            className="ms-auto"
                            onClick={() => {
                                viewItem(step.key)
                                captureWorkItemViewed(thread, item)
                            }}
                            data-attr="work-thread-view-item"
                        >
                            {`View ${item.kind_label}`}
                        </Button>
                    </div>
                )}
                {card}
                {facts.length > 0 && <WorkThreadFacts facts={facts} />}
            </div>
        </section>
    )
}
