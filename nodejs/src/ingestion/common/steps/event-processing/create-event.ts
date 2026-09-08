import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { MAX_GROUP_TYPES_PER_TEAM } from '~/common/groups/group-type-manager'
import { sanitizeString } from '~/common/utils/db/utils'
import { elementsToString, extractElements } from '~/common/utils/elements-chain'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { uuidFromDistinctId } from '~/ingestion/common/persons/person-uuid'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { Properties } from '~/plugin-scaffold'
import { Element, Person, PersonMode, PreIngestionEvent, ProcessedEvent } from '~/types'

const GROUP_INDEX_KEYS = Array.from({ length: MAX_GROUP_TYPES_PER_TEAM }, (_, index) => `$group_${index}`)

const elementsOrElementsChainCounter = new Counter({
    name: 'events_pipeline_elements_or_elements_chain_total',
    help: 'Number of times elements or elements_chain appears on event',
    labelNames: ['type'],
})

export function getElementsChain(properties: Properties): string {
    /*
    We're deprecating $elements in favor of $elements_chain, which doesn't require extra
    processing on the ingestion side and is the way we store elements in ClickHouse.
    As part of that we'll move posthog-js to send us $elements_chain as string directly,
    but we still need to support the old way of sending $elements and converting them
    to $elements_chain, while everyone hasn't upgraded.
    */
    let elementsChain = ''
    if (properties['$elements_chain']) {
        elementsChain = properties['$elements_chain']
        elementsOrElementsChainCounter.labels('elements_chain').inc()
    } else if (properties['$elements']) {
        const elements: Record<string, any>[] | undefined = properties['$elements']
        let elementsList: Element[] = []
        if (elements && elements.length) {
            elementsList = extractElements(elements)
            elementsChain = elementsToString(elementsList)
        }
        elementsOrElementsChainCounter.labels('elements').inc()
    }
    delete properties['$elements_chain']
    delete properties['$elements']
    return elementsChain
}

/** A force upgrade only happens when the client asked for propertyless, and it overrides that ask. */
export function resolvePersonMode(person: Person | undefined, processPerson: boolean): PersonMode {
    if (person?.force_upgrade) {
        return 'force_upgrade'
    }
    return processPerson ? 'full' : 'propertyless'
}

/**
 * Group data cannot survive on a personless event: the group steps skip enrichment when
 * `processPerson` is false, and `createEvent` strips every `$group_N` key the sender
 * supplied, so the event reaches ClickHouse with no group columns and group-scoped
 * insights never see it. Report the loss, because the sender has no other signal.
 */
export function detectIgnoredGroups(
    preIngestionEvent: PreIngestionEvent,
    processPerson: boolean
): PipelineWarning | null {
    if (processPerson) {
        return null
    }

    const properties = preIngestionEvent.properties ?? {}
    const groups = properties.$groups
    const groupTypes =
        typeof groups === 'object' && groups !== null && !Array.isArray(groups) ? Object.keys(groups) : []

    if (groupTypes.length === 0 && !GROUP_INDEX_KEYS.some((key) => key in properties)) {
        return null
    }

    return {
        type: 'groups_ignored_when_process_person_profile_is_false',
        details: {
            eventUuid: preIngestionEvent.eventUuid,
            distinctId: preIngestionEvent.distinctId,
            event: preIngestionEvent.event,
            // `$groups` can hold any number of keys, but only MAX_GROUP_TYPES_PER_TEAM
            // of them could ever resolve to a group column, so the rest only add size.
            groupTypes: groupTypes.slice(0, MAX_GROUP_TYPES_PER_TEAM).map((groupType) => sanitizeString(groupType)),
        },
        // No `key`: the limiter's bucket map never evicts, so a client-supplied key
        // would grow it without bound. Debounce per team and type instead.
    }
}

export function createEvent(
    preIngestionEvent: PreIngestionEvent,
    person: Person | undefined,
    processPerson: boolean,
    historicalMigration: boolean,
    capturedAt: Date | null
): ProcessedEvent {
    const { eventUuid: uuid, event, teamId, projectId, distinctId, properties, timestamp } = preIngestionEvent

    let elementsChain = ''
    try {
        elementsChain = getElementsChain(properties)
    } catch (error) {
        captureException(error, { tags: { team_id: teamId } })
        logger.warn('⚠️', 'Failed to process elements', {
            uuid,
            teamId: teamId,
            properties,
            error,
        })
    }

    let eventPersonProperties: Record<string, unknown> = {}
    if (processPerson && person) {
        eventPersonProperties = {
            ...person.properties,
            // For consistency, we'd like events to contain the properties that they set, even if those were changed
            // before the event is ingested.
            ...(properties.$set || {}),
        }
    } else if (!processPerson) {
        // TODO: Move this into `normalizeEventStep` where it belongs, but the code structure
        // and tests demand this for now.
        for (const key of GROUP_INDEX_KEYS) {
            delete properties[key]
        }
    }

    // Use person UUID if available, otherwise generate deterministic UUID from distinct_id
    const personId = person?.uuid ?? uuidFromDistinctId(teamId, distinctId)

    const processedEvent: ProcessedEvent = {
        uuid,
        event,
        properties: properties ?? {},
        timestamp,
        team_id: teamId,
        project_id: projectId,
        distinct_id: distinctId,
        elements_chain: elementsChain,
        created_at: DateTime.utc(),
        captured_at: capturedAt,
        person_id: personId,
        person_properties: eventPersonProperties,
        person_created_at: person?.created_at ?? null,
        person_mode: resolvePersonMode(person, processPerson),
        // Only include historical_migration when true to avoid bloating messages
        ...(historicalMigration ? { historical_migration: true } : {}),
    }

    return processedEvent
}
