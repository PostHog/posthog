import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { RestrictionType, eventIngestionRestrictionLogic } from 'lib/logic/eventIngestionRestrictionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { featureFlagPersonlessWarningLogic } from './featureFlagPersonlessWarningLogic'

const personProperty = (key: string): AnyPropertyFilter => ({
    key,
    type: PropertyFilterType.Person,
    operator: PropertyOperator.Exact,
    value: 'value',
})

describe('featureFlagPersonlessWarningLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        ['no personless signal', false, [], null],
        ['project-wide opt out', true, [], 'project-opt-out'],
        [
            'ingestion restriction that skips person processing',
            false,
            [{ restriction_type: RestrictionType.SKIP_PERSON_PROCESSING }],
            'ingestion-restriction',
        ],
        [
            'ingestion restriction that keeps person processing',
            false,
            [{ restriction_type: RestrictionType.DROP_EVENT_FROM_INGESTION }],
            null,
        ],
    ])('reports %s', async (_name, optedOut, restrictions, expected) => {
        useMocks({ get: { '/api/environments/:team_id/event_ingestion_restrictions/': restrictions } })

        const logic = featureFlagPersonlessWarningLogic({ properties: [personProperty('email')] })
        logic.mount()
        teamLogic.actions.updateCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, person_processing_opt_out: optedOut })
        eventIngestionRestrictionLogic().values.eventIngestionRestrictions

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ personlessReason: expected })
    })

    it('names only the person properties that need a stored profile', () => {
        useMocks({ get: { '/api/environments/:team_id/event_ingestion_restrictions/': [] } })

        const logic = featureFlagPersonlessWarningLogic({
            properties: [
                personProperty('email'),
                personProperty('email'),
                personProperty('$geoip_country_name'),
                {
                    key: 'plan',
                    type: PropertyFilterType.Group,
                    group_type_index: 0,
                    operator: PropertyOperator.Exact,
                    value: 'pro',
                },
                { key: 'id', type: PropertyFilterType.Cohort, operator: PropertyOperator.In, value: 12 },
            ],
        })
        logic.mount()

        expectLogic(logic).toMatchValues({ storedPropertyKeys: ['email'], targetsCohort: true })
    })
})
