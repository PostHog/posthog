import { useActions } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type {
    WorkHelperModeEnumApi,
    WorkOptionApi,
    WorkStepApi,
    WorkThreadApi,
} from 'products/today/frontend/generated/api.schemas'

import { captureWorkOptionRun, captureWorkPromptShown } from './workThreadEvents'
import { WorkThreadFacts } from './WorkThreadFacts'
import { workThreadLogic } from './workThreadLogic'
import type { WorkRunActionHandler } from './workThreadTypes'

const MODE_TEXT: Record<WorkHelperModeEnumApi, string> = {
    in_place: 'Happens here',
    opens: 'Opens the product, filled in',
}

interface WorkThreadHelperProps {
    thread: WorkThreadApi
    step: WorkStepApi
    option: WorkOptionApi
    onCancel: () => void
    onRunAction: WorkRunActionHandler
}

export function WorkThreadHelper({ thread, step, option, onCancel, onRunAction }: WorkThreadHelperProps): JSX.Element {
    const { closeOption, setPromptShown } = useActions(workThreadLogic({ threadKey: thread.key }))
    const { helper } = option
    const { run } = helper

    const ran = (): void => {
        captureWorkOptionRun(thread, step, option)
        closeOption()
    }

    return (
        <div className="flex flex-col gap-3" data-attr="work-thread-helper">
            <div className="flex flex-col gap-1">
                <Text size="sm" weight="medium" className="m-0">
                    {option.label}
                </Text>
                <Text size="xs" className="m-0">
                    {helper.does}
                </Text>
            </div>
            {helper.fields.length > 0 && <WorkThreadFacts facts={helper.fields} />}
            <Text size="xxs" variant="muted" className="m-0 font-mono">
                {`Supplied by ${helper.product} · ${MODE_TEXT[helper.mode]}`}
            </Text>
            <div className="flex flex-wrap justify-end gap-2">
                <Button variant="outline" onClick={onCancel} data-attr="work-thread-helper-cancel">
                    Cancel
                </Button>
                {helper.mcp_tools.length > 0 && (
                    <Button
                        variant="outline"
                        onClick={() => {
                            setPromptShown(true)
                            captureWorkPromptShown(thread, step, option)
                        }}
                        data-attr="work-thread-helper-copy-prompt"
                    >
                        Copy prompt…
                    </Button>
                )}
                {run.type === 'link' && run.to ? (
                    <Button
                        variant="primary"
                        nativeButton={false}
                        render={<LinkPrimitive to={run.to} />}
                        onClick={ran}
                        data-attr="work-thread-helper-run"
                    >
                        <span>{helper.run_label}</span>
                        <IconArrowRight />
                    </Button>
                ) : (
                    <Button
                        variant="primary"
                        disabledReason={
                            run.type === 'action' && run.action_id ? undefined : 'Nothing is set up to run this option.'
                        }
                        onClick={() => {
                            if (run.action_id) {
                                onRunAction(run.action_id, run.params, option, step)
                                ran()
                            }
                        }}
                        data-attr="work-thread-helper-run"
                    >
                        {helper.run_label}
                    </Button>
                )}
            </div>
        </div>
    )
}
