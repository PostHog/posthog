import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'

export interface TeamSecretKey {
    id: string
    team_id: number
    name: string
    secure_value: string
    created_at: string
    last_used_at: string | null
}

export class TeamSecretKeysManager {
    private lazyLoader: LazyLoader<TeamSecretKey>

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'TeamSecretKeysManager',
            refreshAgeMs: 5 * 60 * 1000, // 5 minutes
            refreshJitterMs: 60 * 1000, // 1 minute
            loader: async (keyIds: string[]) => {
                return await this.fetchSecretKeys(keyIds)
            },
        })
    }

    public async getSecretKey(keyId: string): Promise<TeamSecretKey | null> {
        return this.lazyLoader.get(keyId)
    }

    public async getSecretKeys(keyIds: string[]): Promise<Record<string, TeamSecretKey | null>> {
        return this.lazyLoader.getMany(keyIds)
    }

    private async fetchSecretKeys(keyIds: string[]): Promise<Record<string, TeamSecretKey | null>> {
        const result = await this.postgres.query<TeamSecretKey>(
            PostgresUse.COMMON_READ,
            `SELECT
                id,
                team_id,
                name,
                secure_value,
                created_at,
                last_used_at
            FROM posthog_teamsecretkey
            WHERE id = ANY($1)
            `,
            [keyIds],
            'fetch-secret-keys'
        )

        // Initialize result record with nulls for all requested IDs
        const resultRecord: Record<string, TeamSecretKey | null> = {}
        for (const keyId of keyIds) {
            resultRecord[keyId] = null
        }

        // Fill in actual keys where they exist
        result.rows.forEach((row) => {
            resultRecord[row.id] = row
        })

        return resultRecord
    }
}
