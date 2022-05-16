import * as Sentry from '@sentry/node'

import { Hub } from '../../../types'
import { createEventStep } from './createEventStep'
import { determineShouldBufferStep } from './determineShouldBufferStep'
import { pluginsProcessEventStep } from './pluginsProcessEventStep'
import { prepareEventStep } from './prepareEventStep'
import { runAsyncHandlersStep } from './runAsyncHandlersStep'

type StepParameters<T extends (...args: any[]) => any> = T extends (
    runner: EventPipelineRunner,
    ...args: infer P
) => any
    ? P
    : never

const EVENT_PIPELINE_STEPS = {
    pluginsProcessEventStep,
    prepareEventStep,
    determineShouldBufferStep,
    createEventStep,
    runAsyncHandlersStep,
}

type EventPipelineStepsType = typeof EVENT_PIPELINE_STEPS
type StepType = keyof EventPipelineStepsType
type NextStep<Step extends StepType> = [StepType, StepParameters<EventPipelineStepsType[Step]>]

export type StepResult =
    | null
    | NextStep<'pluginsProcessEventStep'>
    | NextStep<'prepareEventStep'>
    | NextStep<'determineShouldBufferStep'>
    | NextStep<'createEventStep'>
    | NextStep<'runAsyncHandlersStep'>

// :TODO: Timers for every function
// :TODO: DLQ emit for failing on some steps
const EMIT_TO_DLQ_ON_FAILURE: Array<StepType> = ['prepareEventStep', 'determineShouldBufferStep', 'createEventStep']

export class EventPipelineRunner {
    hub: Hub

    constructor(hub: Hub) {
        this.hub = hub
    }

    async runStep<Step extends StepType, ArgsType extends StepParameters<EventPipelineStepsType[Step]>>(
        name: Step,
        ...args: ArgsType
    ): Promise<void> {
        let currentStepName: StepType = name
        let currentArgs: any = args

        while (true) {
            // eslint-disable-next-line @typescript-eslint/ban-ts-comment
            // @ts-ignore
            const stepResult = await EVENT_PIPELINE_STEPS[currentStepName](this, ...currentArgs)

            if (stepResult) {
                ;[currentStepName, currentArgs] = stepResult
            } else {
                break
            }
        }
    }

    nextStep<Step extends keyof EventPipelineStepsType, ArgsType extends StepParameters<EventPipelineStepsType[Step]>>(
        name: Step,
        ...args: ArgsType
    ): NextStep<Step> {
        return [name, args]
    }
}
