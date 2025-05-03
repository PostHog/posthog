import { expectLogic } from 'kea-test-utils'
import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { eventIngestionRestrictionLogic, RestrictionType } from './eventIngestionRestrictionLogic'

jest.mock('lib/api')

describe('eventIngestionRestrictionLogic', () => {
    let logic: ReturnType<typeof eventIngestionRestrictionLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = eventIngestionRestrictionLogic()
    })

    it('loads event ingestion restrictions', async () => {
        jest.spyOn(api, 'get').mockResolvedValue([
            {
                restriction_type: RestrictionType.DROP_EVENT_FROM_INGESTION,
                distinct_ids: ['user1', 'user2'],
            },
        ])

        logic.mount()

        const hasMatchingCall = (api.get as jest.Mock).mock.calls.some(
            (call) => call[0] === 'api/environments/@current/event_ingestion_restrictions/'
        )
        expect(hasMatchingCall).toBe(true)

        await expectLogic(logic)
            .toDispatchActions(['loadEventIngestionRestrictions'])
            .toDispatchActionsInAnyOrder(['loadEventIngestionRestrictionsSuccess'])
            .toMatchValues({
                eventIngestionRestrictions: [
                    {
                        restriction_type: RestrictionType.DROP_EVENT_FROM_INGESTION,
                        distinct_ids: ['user1', 'user2'],
                    },
                ],
                hasAnyRestriction: true,
            })
    })

    it('handles empty restrictions', async () => {
        jest.spyOn(api, 'get').mockResolvedValue([])

        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadEventIngestionRestrictions', 'loadEventIngestionRestrictionsSuccess'])
            .toMatchValues({
                eventIngestionRestrictions: [],
                hasAnyRestriction: false,
            })
    })
})
