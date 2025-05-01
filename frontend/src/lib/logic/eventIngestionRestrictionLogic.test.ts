import { expectLogic, partial } from 'kea-test-utils'
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

        //
        expect(api.get).toHaveBeenCalledWith('api/environments/@current/get_event_ingestion_restriction_config/')

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

    it('handles API errors', async () => {
        const error = new Error('API error')
        jest.spyOn(api, 'get').mockRejectedValue(error)

        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadEventIngestionRestrictions', 'loadEventIngestionRestrictionsFailure'])
            .toMatchValues({
                eventIngestionRestrictions: [],
                eventIngestionRestrictionsError: partial(error),
                hasAnyRestriction: false,
            })
    })
})
