exports.up = (pgm) => {
    // Table for tracking cohort membership - replicating ClickHouse structure
    pgm.createTable('cohort_membership', {
        id: {
            type: 'bigserial',
            primaryKey: true,
        },
        team_id: {
            type: 'bigint',
            notNull: true,
        },
        cohort_id: {
            type: 'bigint',
            notNull: true,
        },
        person_id: {
            type: 'uuid',
            notNull: true,
        },
        in_cohort: {
            type: 'boolean',
            notNull: true,
        },
        last_updated: {
            type: 'timestamp',
            notNull: true,
            default: pgm.func('CURRENT_TIMESTAMP'),
        },
    })

    // Add index on person_id, cohort_id, and team_id for query performance
    pgm.createIndex('cohort_membership', ['person_id', 'cohort_id', 'team_id'])

    // Add unique constraint to prevent duplicate entries
    pgm.addConstraint('cohort_membership', 'cohort_membership_unique', {
        unique: ['team_id', 'cohort_id', 'person_id'],
    })
}

exports.down = (pgm) => {
    pgm.dropTable('cohort_membership')
}
