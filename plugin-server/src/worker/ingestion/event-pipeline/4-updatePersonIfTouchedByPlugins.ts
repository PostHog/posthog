import { PluginEvent } from '@posthog/plugin-scaffold'

import { ForwardedPersonData } from './2-upsertPersonsStep'
import { EventPipelineRunner, StepResult } from './runner'

export async function updatePersonIfTouchedByPlugins(
    runner: EventPipelineRunner,
    event: PluginEvent,
    forwardedPersonData: ForwardedPersonData
): Promise<StepResult> {
    return null
}
