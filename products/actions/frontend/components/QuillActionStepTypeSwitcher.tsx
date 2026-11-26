import { ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { ActionStepType } from '~/types'

import { actionStepTypeOption, withActionStepType } from '../utils/actionStepEdits'

const SCREEN_TYPE_TOOLTIP = 'Screen views from mobile apps ($screen events sent by the mobile SDKs)'

export function QuillActionStepTypeSwitcher({
    step,
    sendStep,
    disabledReason,
}: {
    step: ActionStepType
    sendStep: (step: ActionStepType) => void
    disabledReason?: string
}): JSX.Element {
    const value = actionStepTypeOption(step)

    return (
        <ToggleGroup
            variant="outline"
            aria-label="Match group type"
            className="w-full *:flex-1"
            value={value ? [value] : []}
            onValueChange={(next: string[]) => {
                const nextStep = next[0] ? withActionStepType(step, next[0]) : null
                if (nextStep) {
                    sendStep(nextStep)
                }
            }}
            data-attr="action-type-switcher"
        >
            <ToggleGroupItem value="$pageview" disabledReason={disabledReason} data-attr="action-type-pageview">
                Pageview
            </ToggleGroupItem>
            <ToggleGroupItem value="$autocapture" disabledReason={disabledReason} data-attr="action-type-autocapture">
                Autocapture
            </ToggleGroupItem>
            {disabledReason ? (
                <ToggleGroupItem value="$screen" disabledReason={disabledReason} data-attr="action-type-screen">
                    Mobile screen
                </ToggleGroupItem>
            ) : (
                <Tooltip>
                    <TooltipTrigger render={<ToggleGroupItem value="$screen" data-attr="action-type-screen" />}>
                        Mobile screen
                    </TooltipTrigger>
                    <TooltipContent>{SCREEN_TYPE_TOOLTIP}</TooltipContent>
                </Tooltip>
            )}
            <ToggleGroupItem value="event" disabledReason={disabledReason} data-attr="action-type-other">
                Other events
            </ToggleGroupItem>
        </ToggleGroup>
    )
}
