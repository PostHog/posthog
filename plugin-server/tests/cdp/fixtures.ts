import { randomUUID } from 'crypto'

import { HogFunctionType } from '../../src/cdp/types'
import { Team } from '../../src/types'
import { PostgresRouter } from '../../src/utils/db/postgres'
import { insertRow } from '../helpers/sql'

export const insertHogFunction = async (
    postgres: PostgresRouter,
    team: Team,
    hogFunction: Partial<HogFunctionType> = {}
) => {
    const item: HogFunctionType = {
        id: randomUUID(),
        team_id: team.id,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: 1001,
        enabled: false,
        deleted: false,
        description: '',
        hog: '',
        ...hogFunction,
    }

    await insertRow(postgres, 'posthog_hogfunction', item)

    return item
}
