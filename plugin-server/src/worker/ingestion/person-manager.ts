import LRU from 'lru-cache'

import { ONE_HOUR } from '../../config/constants'
import { PluginsServerConfig } from '../../types'
import { DB } from '../../utils/db/db'

export class PersonManager {
    personSeen: LRU<string, boolean>

    constructor(serverConfig: PluginsServerConfig) {
        this.personSeen = new LRU({
            max: serverConfig.DISTINCT_ID_LRU_SIZE,
            maxAge: 4 * ONE_HOUR,
            updateAgeOnGet: true,
        })
    }

    async isNewPerson(db: DB, teamId: number, distinctId: string): Promise<boolean> {
        const key = `${teamId}::${distinctId}`
        if (this.personSeen.get(key)) {
            return false
        }

        this.personSeen.set(key, true)
        const pdiSelectResult = await db.postgresQuery(
            'SELECT COUNT(*) AS pdicount FROM posthog_persondistinctid WHERE team_id = $1 AND distinct_id = $2',
            [teamId, distinctId],
            'pdicount'
        )
        return parseInt(pdiSelectResult.rows[0].pdicount) === 0
    }
}
