import { Client as CassandraClient, types as CassandraTypes } from 'cassandra-driver'

export interface PersonEventOccurrenceRow {
    team_id: number
    person_id: string
    event_name: string
}

export interface OccurrenceUpdate {
    teamId: number
    personId: string
    eventName: string
}

export class PersonEventOccurrenceRepository {
    constructor(private cassandra: CassandraClient) {}

    /**
     * Maps a Cassandra row to a PersonEventOccurrenceRow
     */
    private mapRowToPersonEventOccurrence(row: any): PersonEventOccurrenceRow {
        return {
            team_id: row.team_id,
            person_id: row.person_id.toString(),
            event_name: row.event_name,
        }
    }

    /**
     * Checks if a person has performed a specific event
     */
    async hasOccurred(params: { teamId: number; personId: string; eventName: string }): Promise<boolean> {
        const { teamId, personId, eventName } = params
        const result = await this.cassandra.execute(
            'SELECT team_id FROM person_event_occurrences WHERE team_id = ? AND person_id = ? AND event_name = ?',
            [teamId, CassandraTypes.Uuid.fromString(personId), eventName],
            { prepare: true }
        )

        return result.rows.length > 0
    }

    /**
     * Gets all events that a person has performed
     */
    async getEventsForPerson(teamId: number, personId: string): Promise<PersonEventOccurrenceRow[]> {
        const result = await this.cassandra.execute(
            'SELECT team_id, person_id, event_name FROM person_event_occurrences WHERE team_id = ? AND person_id = ?',
            [teamId, CassandraTypes.Uuid.fromString(personId)],
            { prepare: true }
        )

        return result.rows.map((row) => this.mapRowToPersonEventOccurrence(row))
    }

    /**
     * Batch inserts multiple person event occurrences
     * Uses regular INSERT - compaction will handle duplicates efficiently
     */
    async batchInsertOccurrences(updates: OccurrenceUpdate[]): Promise<void> {
        if (updates.length === 0) {
            return
        }

        const batch = updates.map((update) => ({
            query: 'INSERT INTO person_event_occurrences (team_id, person_id, event_name) VALUES (?, ?, ?)',
            params: [update.teamId, CassandraTypes.Uuid.fromString(update.personId), update.eventName],
        }))

        await this.cassandra.batch(batch, { prepare: true, logged: false })
    }
}
