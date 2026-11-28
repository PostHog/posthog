import { Text } from '@posthog/quill'

import type { WorkStepApi, WorkThreadApi } from 'products/today/frontend/generated/api.schemas'

import { WorkThreadOption } from './WorkThreadOption'
import type { WorkRunActionHandler } from './workThreadTypes'

interface WorkThreadOptionsProps {
    thread: WorkThreadApi
    step: WorkStepApi
    onRunAction: WorkRunActionHandler
}

export function WorkThreadOptions({ thread, step, onRunAction }: WorkThreadOptionsProps): JSX.Element | null {
    const next = step.options.filter((option) => option.kind === 'next')
    const alongside = step.options.filter((option) => option.kind === 'alongside')
    const primaryKey = next.find((option) => !option.gate)?.key

    if (next.length === 0 && alongside.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-4" data-attr="work-thread-options">
            {next.length > 0 && (
                <section className="flex flex-col gap-2">
                    <Text size="xs" weight="medium" className="m-0">
                        {next.length > 1 ? 'Next step, pick one' : 'Next step'}
                    </Text>
                    <ul className="m-0 flex list-none flex-col gap-2 p-0">
                        {next.map((option) => (
                            <WorkThreadOption
                                key={option.key}
                                thread={thread}
                                step={step}
                                option={option}
                                primary={option.key === primaryKey}
                                onRunAction={onRunAction}
                            />
                        ))}
                    </ul>
                </section>
            )}
            {alongside.length > 0 && (
                <section className="flex flex-col gap-2">
                    <Text size="xs" weight="medium" className="m-0">
                        Can run alongside
                    </Text>
                    <ul className="m-0 flex list-none flex-col gap-2 p-0">
                        {alongside.map((option) => (
                            <WorkThreadOption
                                key={option.key}
                                thread={thread}
                                step={step}
                                option={option}
                                primary={false}
                                onRunAction={onRunAction}
                            />
                        ))}
                    </ul>
                </section>
            )}
        </div>
    )
}
