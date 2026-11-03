import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ProductIntentType } from '~/types'

import { applyLaterAppContext } from './laterAppContext'
import { teamLogic } from './teamLogic'
import { userLogic } from './userLogic'

const LATER_INTENTS = [{ product_type: ProductKey.SESSION_REPLAY }] as ProductIntentType[]

describe('applyLaterAppContext', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        ['the page team', MOCK_TEAM_ID, LATER_INTENTS],
        ['a team the user switched away from', MOCK_TEAM_ID + 1, undefined],
    ])('merges the later fields into the mounted logics for %s', async (_, requestedTeamId, expectedIntents) => {
        delete window.POSTHOG_APP_CONTEXT?.current_team?.product_intents
        delete window.POSTHOG_APP_CONTEXT?.has_person_email
        userLogic.mount()
        teamLogic.mount()
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])

        applyLaterAppContext(requestedTeamId, {
            current_user: { is_2fa_enabled: true, has_sso_enforcement: true },
            current_team: { product_intents: LATER_INTENTS },
            has_person_email: true,
        })

        expect(userLogic.values.user).toMatchObject({ is_2fa_enabled: true, has_sso_enforcement: true })
        expect(teamLogic.values.currentTeam?.product_intents).toEqual(expectedIntents)
        expect(window.POSTHOG_APP_CONTEXT?.has_person_email).toBe(expectedIntents ? true : undefined)
    })
})
