import { useActions, useValues } from 'kea'

import { Button, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import type { WorkOptionApi, WorkStepApi, WorkThreadApi } from 'products/today/frontend/generated/api.schemas'

import { captureWorkOptionDismissed, captureWorkOptionOpened } from './workThreadEvents'
import { WorkThreadHelper } from './WorkThreadHelper'
import { WorkThreadHelperPrompt } from './WorkThreadHelperPrompt'
import { workThreadLogic } from './workThreadLogic'
import type { WorkRunActionHandler } from './workThreadTypes'

interface WorkThreadOptionProps {
    thread: WorkThreadApi
    step: WorkStepApi
    option: WorkOptionApi
    primary: boolean
    onRunAction: WorkRunActionHandler
}

export function WorkThreadOption({ thread, step, option, primary, onRunAction }: WorkThreadOptionProps): JSX.Element {
    const logic = workThreadLogic({ threadKey: thread.key })
    const { openOptionRef, promptShown } = useValues(logic)
    const { openOption, closeOption } = useActions(logic)
    const open = openOptionRef?.stepKey === step.key && openOptionRef.optionKey === option.key

    const dismiss = (): void => {
        captureWorkOptionDismissed(thread, step, option, promptShown)
        closeOption()
    }

    return (
        <li className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Popover
                open={open}
                onOpenChange={(nextOpen) => {
                    if (nextOpen && !option.gate) {
                        openOption(step.key, option.key)
                        captureWorkOptionOpened(thread, step, option)
                    } else if (!nextOpen && open) {
                        dismiss()
                    }
                }}
            >
                <PopoverTrigger
                    render={
                        <Button
                            variant={primary ? 'primary' : 'outline'}
                            disabledReason={option.gate}
                            className="max-w-full"
                            data-attr={`work-thread-option-${option.key}`}
                        />
                    }
                >
                    <span className="truncate">{`${option.label}…`}</span>
                </PopoverTrigger>
                <PopoverContent side="bottom" align="start" className="w-96" aria-label={option.label}>
                    {open && promptShown ? (
                        <WorkThreadHelperPrompt thread={thread} step={step} option={option} />
                    ) : (
                        <WorkThreadHelper
                            thread={thread}
                            step={step}
                            option={option}
                            onCancel={dismiss}
                            onRunAction={onRunAction}
                        />
                    )}
                </PopoverContent>
            </Popover>
            <Text size="xs" variant="muted" className="m-0 min-w-0 flex-1 basis-64 @max-md/work-thread:basis-full">
                {option.gate ?? option.why}
            </Text>
        </li>
    )
}
