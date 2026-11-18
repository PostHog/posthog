import { decideProcessPerson } from '~/common/persons/person-utils'
import { normalizeProcessPerson } from '~/common/utils/event'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { PipelineResult, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { EventHeaders, Team } from '~/types'

const PERSON_ONLY_EVENTS = ['$identify', '$create_alias', '$merge_dangerously', '$groupidentify']

type NormalizeProcessPersonFlagInput = {
    event: PluginEvent
    team: Team
    headers: EventHeaders
}

type NormalizeProcessPersonFlagOutput = {
    processPerson: boolean
    processPersonExplicitlyTrue: boolean
    forceDisablePersonProcessing: boolean
}

export function createNormalizeProcessPersonFlagStep<TInput extends NormalizeProcessPersonFlagInput>(): ProcessingStep<
    TInput,
    TInput & NormalizeProcessPersonFlagOutput
> {
    return function normalizeProcessPersonFlagStep(
        input: TInput
    ): Promise<PipelineResult<TInput & NormalizeProcessPersonFlagOutput>> {
        const event = input.event
        const warnings: PipelineWarning[] = []
        let normalizedEvent = event
        // Captured here because normalizeProcessPerson later deletes the property for
        // personful events, and downstream steps need to know it was explicitly set.
        const processPersonExplicitlyTrue = event.properties?.$process_person_profile === true

        const decision = decideProcessPerson(event, input.headers)
        const processPerson = decision.processPerson
        const forceDisablePersonProcessing = !decision.processPerson && decision.reason === 'header'

        if (!decision.processPerson && decision.reason === 'property') {
            if (PERSON_ONLY_EVENTS.includes(event.event)) {
                const details = {
                    eventUuid: event.uuid,
                    event: event.event,
                    distinctId: event.distinct_id,
                }

                // applyPersonProcessingRestrictionsStep stamps $process_person_profile=false
                // for an opted-out team, so the property alone cannot say who set it.
                if (input.team.person_processing_opt_out === true) {
                    warnings.push({
                        type: 'event_dropped_person_processing_disabled',
                        details,
                        // The cause is a standing project setting, so debounce per event name.
                        key: event.event,
                        alwaysSend: false,
                    })

                    return Promise.resolve(drop('person_processing_disabled', [], warnings))
                }

                warnings.push({
                    type: 'invalid_event_when_process_person_profile_is_false',
                    details,
                    alwaysSend: true,
                })

                return Promise.resolve(drop('invalid_event_for_flags', [], warnings))
            }

            // If person processing is disabled, go ahead and remove person related keys before
            // any plugins have a chance to see them.
            normalizedEvent = normalizeProcessPerson(event, processPerson)
        } else if (decision.processPerson && decision.invalid) {
            // Anything other than `true` or `false` is invalid, and the default (true) will be
            // used.
            warnings.push({
                type: 'invalid_process_person_profile',
                details: {
                    eventUuid: event.uuid,
                    event: event.event,
                    distinctId: event.distinct_id,
                    $process_person_profile: decision.invalid.value,
                    message: 'Only a boolean value is valid for the $process_person_profile property',
                },
                alwaysSend: false,
            })
        }

        return Promise.resolve(
            ok(
                {
                    ...input,
                    event: normalizedEvent,
                    processPerson,
                    processPersonExplicitlyTrue,
                    forceDisablePersonProcessing,
                },
                [],
                warnings
            )
        )
    }
}
