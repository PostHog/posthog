import jsonData from './recording_events.json'

export default {
    columns: [
        'uuid',
        'event',
        'timestamp',
        'elements_chain',
        'properties.$window_id',
        'properties.$current_url',
        'properties.$event_name',
    ],
    hasMore: false,
    results: jsonData.map((x) => [
        x.id,
        x.event,
        x.timestamp,
        x.elements_hash,
        x.properties.$window_id,
        x.properties.$current_url,
        x.properties.$event_name,
    ]),
    types: ['UUID', 'String', "DateTime64(6, 'UTC')", 'String', 'String', 'String', 'String'],
}
