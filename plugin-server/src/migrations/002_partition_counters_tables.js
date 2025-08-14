exports.up = (pgm) => {
    // Create partitioned table structure for person_performed_events
    pgm.sql(`
        CREATE TABLE person_performed_events_partitioned (
            team_id INTEGER NOT NULL,
            person_id UUID NOT NULL,
            event_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        ) PARTITION BY HASH (team_id)
    `)

    // Create partitions (100 partitions for hash)
    pgm.sql(`
        DO $$
        BEGIN
            FOR i IN 0..99 LOOP
                EXECUTE format('CREATE TABLE person_performed_events_p%s PARTITION OF person_performed_events_partitioned 
                                FOR VALUES WITH (modulus 100, remainder %s)', i, i);
            END LOOP;
        END $$
    `)

    // Add constraints to partitioned table (automatically inherited by partitions)
    pgm.addConstraint('person_performed_events_partitioned', 'person_performed_events_partitioned_unique', {
        unique: ['team_id', 'person_id', 'event_name'],
    })

    // Create partitioned table structure for behavioural_filter_matched_events
    pgm.sql(`
        CREATE TABLE behavioural_filter_matched_events_partitioned (
            team_id INTEGER NOT NULL,
            person_id UUID NOT NULL,
            filter_hash TEXT NOT NULL,
            date DATE NOT NULL,
            counter INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        ) PARTITION BY HASH (team_id)
    `)

    // Create partitions (100 partitions for hash)
    pgm.sql(`
        DO $$
        BEGIN
            FOR i IN 0..99 LOOP
                EXECUTE format('CREATE TABLE behavioural_filter_matched_events_p%s PARTITION OF behavioural_filter_matched_events_partitioned 
                                FOR VALUES WITH (modulus 100, remainder %s)', i, i);
            END LOOP;
        END $$
    `)

    // Add constraints to partitioned table (automatically inherited by partitions)
    pgm.addConstraint(
        'behavioural_filter_matched_events_partitioned',
        'behavioural_filter_matched_events_partitioned_unique',
        {
            unique: ['team_id', 'person_id', 'filter_hash', 'date'],
        }
    )

    // Create indexes on partitioned tables (automatically inherited by partitions)
    pgm.createIndex('person_performed_events_partitioned', ['team_id', 'person_id'], {
        name: 'idx_person_performed_events_partitioned_team_person',
    })

    pgm.createIndex('behavioural_filter_matched_events_partitioned', ['team_id', 'person_id'], {
        name: 'idx_behavioural_filter_partitioned_team_person',
    })
}

exports.down = (pgm) => {
    // Drop partitioned tables and all their partitions
    pgm.dropTable('behavioural_filter_matched_events_partitioned', { cascade: true })
    pgm.dropTable('person_performed_events_partitioned', { cascade: true })
}
