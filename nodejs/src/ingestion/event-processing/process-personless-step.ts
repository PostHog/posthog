import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { Person, Team } from '../../types'
import { processPersonlessStep } from '../../worker/ingestion/event-pipeline/processPersonlessStep'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResult, isOkResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export type ProcessPersonlessInput = {
    normalizedEvent: PluginEvent
    team: Team
    timestamp: DateTime
    processPerson: boolean
    forceDisablePersonProcessing: boolean
}

export type ProcessPersonlessOutput = {
    personlessPerson?: Person
}

export function createProcessPersonlessStep<TInput extends ProcessPersonlessInput>(
    personsStore: PersonsStore
): ProcessingStep<TInput, TInput & ProcessPersonlessOutput> {
    return async function processPersonlessStepWrapper(
        input: TInput
    ): Promise<PipelineResult<TInput & ProcessPersonlessOutput>> {
        if (input.processPerson) {
            return ok(input)
        }

        const { normalizedEvent, team, timestamp, forceDisablePersonProcessing } = input

        const result = await processPersonlessStep(
            normalizedEvent,
            team,
            timestamp,
            personsStore,
            forceDisablePersonProcessing
        )

        if (isOkResult(result)) {
            return ok({
                ...input,
                personlessPerson: result.value,
            })
        }

        return result
    }
}
