import { normalizeProcessPerson } from '../../utils/event'
import { PerDistinctIdPipelineInput } from '../ingestion-consumer'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { PipelineResult, drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { EventPipelineRunnerInput } from './event-pipeline-runner-v1-step'

export function createNormalizeProcessPersonFlagStep(): ProcessingStep<
    PerDistinctIdPipelineInput,
    EventPipelineRunnerInput
> {
    return function normalizeProcessPersonFlagStep(
        input: PerDistinctIdPipelineInput
    ): Promise<PipelineResult<EventPipelineRunnerInput>> {
        const event = input.event
        const warnings: PipelineWarning[] = []
        const forceDisablePersonProcessing = input.headers.force_disable_person_processing === true
        let processPerson = true // The default.
        let normalizedEvent = event

        // Check if force_disable_person_processing header is set to true
        if (forceDisablePersonProcessing) {
            processPerson = false
        } else {
            // Set either at capture time, or in the populateTeamData step, if team-level opt-out is enabled.
            if (event.properties && '$process_person_profile' in event.properties) {
                const propValue = event.properties.$process_person_profile
                if (propValue === true) {
                    // This is the default, and `true` is one of the two valid values.
                } else if (propValue === false) {
                    // Only a boolean `false` disables person processing.
                    processPerson = false

                    if (['$identify', '$create_alias', '$merge_dangerously', '$groupidentify'].includes(event.event)) {
                        warnings.push({
                            type: 'invalid_event_when_process_person_profile_is_false',
                            details: {
                                eventUuid: event.uuid,
                                event: event.event,
                                distinctId: event.distinct_id,
                            },
                            alwaysSend: true,
                        })

                        return Promise.resolve(drop('invalid_event_for_flags', [], warnings))
                    }

                    // If person processing is disabled, go ahead and remove person related keys before
                    // any plugins have a chance to see them.
                    normalizedEvent = normalizeProcessPerson(event, processPerson)
                } else {
                    // Anything other than `true` or `false` is invalid, and the default (true) will be
                    // used.
                    warnings.push({
                        type: 'invalid_process_person_profile',
                        details: {
                            eventUuid: event.uuid,
                            event: event.event,
                            distinctId: event.distinct_id,
                            $process_person_profile: propValue,
                            message: 'Only a boolean value is valid for the $process_person_profile property',
                        },
                        alwaysSend: false,
                    })
                }
            }
        }

        return Promise.resolve(
            ok(
                {
                    ...input,
                    event: normalizedEvent,
                    processPerson,
                    forceDisablePersonProcessing,
                },
                [],
                warnings
            )
        )
    }
}
