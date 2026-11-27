import { urls } from 'scenes/urls'

import { IngestionWarningV2Sample } from './ingestionWarningsV2Logic'

export interface SampleEntity {
    label: string
    value: string
    /** Where the value links to. Without one, the value is copyable instead. */
    to?: string
}

/** The person, event and group a sample points at, in the order the chips show them. */
export function sampleEntities(sample: IngestionWarningV2Sample): SampleEntity[] {
    const entities: SampleEntity[] = []
    if (sample.distinct_id) {
        entities.push({
            label: 'distinct_id',
            value: sample.distinct_id,
            to: urls.personByDistinctId(sample.distinct_id),
        })
    }
    if (sample.person_id) {
        entities.push({ label: 'person_id', value: sample.person_id, to: urls.personByUUID(sample.person_id) })
    }
    if (sample.event_uuid) {
        entities.push({
            label: 'event_uuid',
            value: sample.event_uuid,
            to: urls.event(sample.event_uuid, sample.timestamp),
        })
    }
    if (sample.group_key) {
        entities.push({ label: 'group_key', value: sample.group_key })
    }
    return entities
}
