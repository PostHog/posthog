import { Text } from '@posthog/quill'

import type { WorkLineApi, WorkStepApi, WorkThreadApi } from 'products/today/frontend/generated/api.schemas'

import { WorkThreadStep } from './WorkThreadStep'
import type { WorkRunActionHandler } from './workThreadTypes'

interface WorkThreadLineProps {
    thread: WorkThreadApi
    line: WorkLineApi
    renderEvidence?: (step: WorkStepApi) => JSX.Element | null
    onRunAction: WorkRunActionHandler
}

export function WorkThreadLine({ thread, line, renderEvidence, onRunAction }: WorkThreadLineProps): JSX.Element {
    return (
        <ol className="m-0 flex list-none flex-col p-0" data-attr="work-thread-line">
            {line.steps.map((step) => (
                <WorkThreadStep
                    key={step.key}
                    thread={thread}
                    line={line}
                    step={step}
                    renderEvidence={renderEvidence}
                    onRunAction={onRunAction}
                >
                    {step.alongside.map((alongsideLine) => (
                        <section
                            key={alongsideLine.key}
                            className="flex flex-col gap-2"
                            aria-label={`Alongside ${step.title}`}
                            data-attr="work-thread-alongside"
                        >
                            <Text size="xxs" variant="muted" className="m-0 font-mono">
                                Alongside
                            </Text>
                            <WorkThreadLine
                                thread={thread}
                                line={alongsideLine}
                                renderEvidence={renderEvidence}
                                onRunAction={onRunAction}
                            />
                        </section>
                    ))}
                </WorkThreadStep>
            ))}
        </ol>
    )
}
