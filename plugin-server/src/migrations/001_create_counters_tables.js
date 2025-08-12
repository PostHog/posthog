exports.up = (pgm) => {
    // Table for person performed events
    pgm.createTable('person_performed_events', {
        team_id: {
            type: 'integer',
            notNull: true,
        },
        person_id: {
            type: 'uuid',
            notNull: true,
        },
        event_name: {
            type: 'text',
            notNull: true,
        },
    })

    // Add composite primary key
    pgm.addConstraint('person_performed_events', 'person_performed_events_pkey', {
        primaryKey: ['team_id', 'person_id', 'event_name'],
    })

    // Index for efficient lookups by team_id and person_id
    pgm.createIndex('person_performed_events', ['team_id', 'person_id'], {
        name: 'idx_person_performed_events_team_person',
    })

    // Table for behavioural filter matched events
    pgm.createTable('behavioural_filter_matched_events', {
        team_id: {
            type: 'integer',
            notNull: true,
        },
        person_id: {
            type: 'uuid',
            notNull: true,
        },
        filter_hash: {
            type: 'text',
            notNull: true,
        },
        date: {
            type: 'date',
            notNull: true,
        },
        counter: {
            type: 'integer',
            notNull: true,
            default: 0,
        },
    })

    // Add composite primary key
    pgm.addConstraint('behavioural_filter_matched_events', 'behavioural_filter_matched_events_pkey', {
        primaryKey: ['team_id', 'person_id', 'filter_hash', 'date'],
    })

    // Index for queries by just team_id and person_id
    pgm.createIndex('behavioural_filter_matched_events', ['team_id', 'person_id'], {
        name: 'idx_behavioural_filter_team_person',
    })
}

exports.down = (pgm) => {
    pgm.dropTable('behavioural_filter_matched_events')
    pgm.dropTable('person_performed_events')
}
