import { PluginEvent } from '@posthog/plugin-scaffold'

import { KAFKA_BUFFER } from '../../../config/kafka-topics'
import { Hub, IngestionPersonData, TeamId } from '../../../types'
import { status } from '../../../utils/status'
import { LazyPersonContainer } from '../lazy-person-container'
import { EventPipelineRunner } from './runner'

export async function emitToBufferStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    shouldBuffer: (
        hub: Hub,
        event: PluginEvent,
        person: IngestionPersonData | undefined,
        teamId: TeamId
    ) => boolean = shouldSendEventToBuffer
): Promise<[PluginEvent, LazyPersonContainer] | null> {
    status.debug('🔁', 'Running emitToBufferStep', { event: event.event, distinct_id: event.distinct_id })

    // TODO: REMOVE Incident mitigation details in https://posthog.slack.com/archives/C0185UNBSJZ/p1675841292796619
    if (
        event.event == '$groupidentify' &&
        event.team_id == 19279 &&
        event.distinct_id == '$client_CLT-0cad9ed8-eee6-4ef0-a3b6-0f77761f1439'
    ) {
        runner.hub.statsd?.increment('groupidentify-blackhole-incident-mitigation')
        return null
    }

    const personContainer = new LazyPersonContainer(event.team_id, event.distinct_id, runner.hub)

    if (
        process.env.POE_EMBRACE_JOIN_FOR_TEAMS === '*' ||
        process.env.POE_EMBRACE_JOIN_FOR_TEAMS?.split(',').includes(event.team_id.toString())
    ) {
        // https://docs.google.com/document/d/12Q1KcJ41TicIwySCfNJV5ZPKXWVtxT7pzpB3r9ivz_0
        // We're not using the buffer anymore
        // instead we'll (if within timeframe) merge into the newer personId

        // TODO: remove this step and runner env once we're confident that the new
        // ingestion pipeline is working well for all teams.
        runner.poEEmbraceJoin = true
        return [event, personContainer]
    }

    const person = await personContainer.get()
    if (shouldBuffer(runner.hub, event, person, event.team_id)) {
        const processEventAt = Date.now() + runner.hub.BUFFER_CONVERSION_SECONDS * 1000
        status.debug('🔁', 'Emitting event to buffer', {
            event: event.event,
            eventId: event.uuid,
            processEventAt,
        })

        // Set `posthog_team.ingested_event` early such that e.g. the onboarding
        // flow is allowed to proceed as soon as there has been an event starts
        // processed as opposed to having to wait for the event to be buffered.
        const team = await runner.hub.teamManager.fetchTeam(event.team_id)
        if (team) {
            await runner.hub.teamManager.setTeamIngestedEvent(team, event.properties || {})
        }

        // TODO: handle delaying offset commit for this message, according to
        // producer acknowledgement. It's a little tricky as it stands as we do
        // not have the a reference to resolveOffset here. Rather than do a
        // refactor I'm just going to let this hang and resolve as a followup.
        await runner.hub.kafkaProducer.queueMessage({
            topic: KAFKA_BUFFER,
            messages: [
                {
                    key: event.distinct_id,
                    value: JSON.stringify(event),
                    headers: { processEventAt: processEventAt.toString(), eventId: event.uuid },
                },
            ],
        })

        runner.hub.statsd?.increment('events_sent_to_buffer')
        return null
    } else {
        return [event, personContainer]
    }
}

/** Returns whether the event should be delayed using the event buffer mechanism.
 *
 * Why? Non-anonymous not merging events with no existing person matching their distinct ID are sent to a buffer.
 * This is so that we can better handle the case where one client uses a fresh distinct ID before another client
 * has managed to send the $identify event aliasing an existing anonymous distinct ID to the fresh distinct ID.
 *
 * This is easier to see with an example scenario:
 * 1. User visits signup page,
 *    in turn frontend captures anonymous `$pageview` for distinct ID `XYZ` (anonymous distinct ID = device ID).
 *    This event gets person ID A.
 * 2. User click signup button, initiating in a backend request,
 *    in turn frontend captures anonymous `$autocapture` (click) for distinct ID `XYZ`.
 *    This event gets person ID A.
 * 3. Signup request is processed in the backend,
 *    in turn backend captures identified `signup` for distinct ID `alice@example.com`.
 *    OOPS! We haven't seen `alice@example.com` before, so this event gets person ID B.
 * 4. Signup request finishes successfully,
 *    in turn frontend captures identified `$identify` aliasing distinct ID `XYZ` to `alice@example.com`.
 *    This event gets person ID A.
 *
 * Without a buffer, the event from step 3 gets a new person ID, which messes up analysis by unique users.
 * By delaying the event from step 3, all events get the desired person ID A.
 *
 * More context: https://github.com/PostHog/posthog/issues/9182
 */
export function shouldSendEventToBuffer(
    hub: Hub,
    event: PluginEvent,
    person: IngestionPersonData | undefined,
    teamId: TeamId
): boolean {
    // Libraries by default create a unique id for this `type-name_value` for $groupidentify,
    // we don't want to buffer these to make group properties available asap
    // identify and alias are identical and could merge the person - the sooner
    // we update the person_id the better
    const eventProperties = event.properties ?? {}

    const isGroupIdentifyEvent = event.event == '$groupidentify'

    // KLUDGE: A merging $identify event is one where the new ID is different from the old ID. Ideally all $identify
    // events would be like this, but in reality some libraries use $identify events to set user properties
    const isMergingIdentifyEvent =
        event.event == '$identify' &&
        '$anon_distinct_id' in eventProperties &&
        eventProperties['$anon_distinct_id'] !== event.distinct_id

    const isMergingAliasEvent =
        event.event == `$create_alias` && 'alias' in eventProperties && eventProperties['alias'] !== event.distinct_id

    const conversionBufferDisabled = !hub.CONVERSION_BUFFER_ENABLED && !hub.conversionBufferEnabledTeams.has(teamId)
    const statsdExtra: { [key: string]: string } = {
        teamId: event.team_id.toString(),
        isBufferDisabled: conversionBufferDisabled.toString(),
        personExists: (!!person).toString(),
        isGroupIdentifyEvent: isGroupIdentifyEvent.toString(),
        isMergingAliasEvent: isMergingAliasEvent.toString(),
        isMergingIdentifyEvent: isMergingIdentifyEvent.toString(),
    }
    if (conversionBufferDisabled || person || isGroupIdentifyEvent || isMergingIdentifyEvent || isMergingAliasEvent) {
        status.debug('🔁', 'Not sending event to buffer', {
            event,
            person,
            conversionBufferDisabled,
            isGroupIdentifyEvent,
            isMergingIdentifyEvent,
            isMergingAliasEvent,
            personExists: !!person,
        })
        hub.statsd?.increment('conversion_events_no_buffer', statsdExtra)
        return false
    }

    const shouldBufferAnonymousEvents = teamId <= hub.MAX_TEAM_ID_TO_BUFFER_ANONYMOUS_EVENTS_FOR
    statsdExtra['shouldBufferAnonymous'] = shouldBufferAnonymousEvents.toString()
    if (shouldBufferAnonymousEvents) {
        hub.statsd?.increment('conversion_events_buffer_size', statsdExtra)
        return true
    }

    // KLUDGE: This definition is not currently not encompassing all anonymous events
    const isAnonymousEvent = event.distinct_id === eventProperties['$device_id']
    statsdExtra['isAnonymous'] = isAnonymousEvent.toString()
    if (isAnonymousEvent) {
        hub.statsd?.increment('conversion_events_no_buffer', statsdExtra)
        return false
    }

    // We do not send events from mobile libraries to the buffer because:
    // a) that wouldn't help with the backend problem outlined above
    // b) because of issues with $device_id in the mobile libraries, we often mislabel events
    //  as being from an identified user when in fact they are not, leading to unnecessary buffering
    const isMobileLibrary = ['posthog-ios', 'posthog-android', 'posthog-react-native', 'posthog-flutter'].includes(
        eventProperties['$lib']
    )
    statsdExtra['isMobileLib'] = isMobileLibrary.toString()
    if (isMobileLibrary) {
        hub.statsd?.increment('conversion_events_no_buffer', statsdExtra)
        return false
    }

    hub.statsd?.increment('conversion_events_buffer_size', statsdExtra)
    return true
}
