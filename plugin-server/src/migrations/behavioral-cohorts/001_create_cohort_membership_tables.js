exports.up = (pgm) => {
    // Table for tracking cohort membership
    pgm.createTable('cohort_membership', {
        team_id: {
            type: 'integer',
            notNull: true,
        },
        cohort_id: {
            type: 'integer',
            notNull: true,
        },
        person_id: {
            type: 'bigint',
            notNull: true,
        },
        is_member: {
            type: 'boolean',
            notNull: true,
            default: true,
        },
        joined_at: {
            type: 'timestamp',
            notNull: true,
            default: pgm.func('CURRENT_TIMESTAMP'),
        },
        left_at: {
            type: 'timestamp',
            notNull: false,
        },
        updated_at: {
            type: 'timestamp',
            notNull: true,
            default: pgm.func('CURRENT_TIMESTAMP'),
        },
    })

    // Add composite primary key
    pgm.addConstraint('cohort_membership', 'cohort_membership_pkey', {
        primaryKey: ['team_id', 'cohort_id', 'person_id'],
    })

    // Add indexes for query performance
    pgm.createIndex('cohort_membership', ['team_id', 'person_id'])
    pgm.createIndex('cohort_membership', ['cohort_id', 'is_member'])
    pgm.createIndex('cohort_membership', 'updated_at')

    // Table for cohort membership change events (for audit/history)
    pgm.createTable('cohort_membership_events', {
        id: {
            type: 'bigserial',
            primaryKey: true,
        },
        team_id: {
            type: 'integer',
            notNull: true,
        },
        cohort_id: {
            type: 'integer',
            notNull: true,
        },
        person_id: {
            type: 'bigint',
            notNull: true,
        },
        event_type: {
            type: 'text',
            notNull: true,
            check: "event_type IN ('entered', 'left')",
        },
        timestamp: {
            type: 'timestamp',
            notNull: true,
            default: pgm.func('CURRENT_TIMESTAMP'),
        },
    })

    // Add indexes for event table
    pgm.createIndex('cohort_membership_events', ['team_id', 'cohort_id', 'person_id'])
    pgm.createIndex('cohort_membership_events', 'timestamp')

    // Add update trigger to maintain updated_at timestamp
    pgm.sql(`
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    `)

    pgm.sql(`
        CREATE TRIGGER update_cohort_membership_updated_at 
        BEFORE UPDATE ON cohort_membership 
        FOR EACH ROW 
        EXECUTE FUNCTION update_updated_at_column();
    `)
}

exports.down = (pgm) => {
    pgm.sql('DROP TRIGGER IF EXISTS update_cohort_membership_updated_at ON cohort_membership')
    pgm.sql('DROP FUNCTION IF EXISTS update_updated_at_column')
    pgm.dropTable('cohort_membership_events')
    pgm.dropTable('cohort_membership')
}
