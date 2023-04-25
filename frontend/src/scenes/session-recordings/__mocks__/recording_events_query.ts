import jsonData from './recording_events.json'

export default {
    columns: ['uuid', 'event', 'timestamp', 'elements_chain', 'properties.$current_url', 'properties.$window_id'],
    hasMore: false,
    results: [
        [
            '0187b2fd-fb94-0001-71c9-b753810dabd0',
            '$groupidentify',
            '2023-04-24T11:19:59.222Z',
            '',
            'http://localhost:8000/recordings/recent?filters=%7B%22session_recording_duration%22%3A%7B%22operator%22%3A%22gt%22%2C%22value%22%3A1%2C%22type%22%3A%22recording%22%2C%22key%22%3A%22duration%22%7D%2C%22properties%22%3A%5B%5D%2C%22events%22%3A%5B%5D%2C%22actions%22%3A%5B%5D%2C%22date_from%22%3A%22-21d%22%7D#sessionRecordingId=187b2fafe7646cc-054090011a5b32-1d525634-384000-187b2fafe772c0e',
            '187b2fdefe84810-076c13fd099e2f-1d525634-384000-187b2fdefe95183',
        ],
        ...jsonData.map((x) => [
            x.id,
            x.event,
            x.timestamp,
            x.elements_hash,
            x.properties.$current_url,
            x.properties.$window_id,
            ,
        ]),
    ],
    types: ['UUID', 'String', "DateTime64(6, 'UTC')", 'String', 'String', 'String'],
}
