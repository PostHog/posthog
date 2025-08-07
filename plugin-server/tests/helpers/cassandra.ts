import { Client as CassandraClient } from 'cassandra-driver'

/**
 * Test helper functions for Cassandra operations
 */

/**
 * Truncates the behavioral_event_counters table (useful for tests)
 */
export async function truncateBehavioralCounters(cassandra: CassandraClient): Promise<void> {
    await cassandra.execute('TRUNCATE behavioral_event_counters')
}
