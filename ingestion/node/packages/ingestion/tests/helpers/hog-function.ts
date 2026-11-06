import { randomUUID } from 'crypto'

import { HogFunctionType } from '@posthog/hog-engine/cdp/types'
import { getTeamMemberUserId, insertRow } from '@posthog/node-common/testing/sql'
import { PostgresRouter } from '@posthog/node-common/utils/db/postgres'

import { Team } from '~/types'

// Inserts a hog function row the way the Django API would, for tests that run a transformation end to end.
export async function insertHogFunction(
    postgres: PostgresRouter,
    teamId: Team['id'],
    hogFunction: Partial<HogFunctionType>
): Promise<HogFunctionType> {
    const createdById = await getTeamMemberUserId(postgres, teamId)
    return await insertRow(postgres, 'posthog_hogfunction', {
        id: randomUUID(),
        type: 'destination',
        name: 'Hog Function',
        enabled: true,
        hog: '',
        bytecode: [],
        ...hogFunction,
        team_id: teamId,
        description: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: createdById,
        deleted: false,
    })
}
