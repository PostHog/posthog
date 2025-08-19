import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { delay } from 'lib/utils'

import { initKeaTests } from '~/test/init'

import { RestrictionType, eventIngestionRestrictionLogic } from './eventIngestionRestrictionLogic'

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
        logic.values.eventIngestionRestrictions
        await delay(1)
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
                hasProjectNoticeRestriction: true,
            })
    })

    it('handles SKIP_PERSON_PROCESSING restriction', async () => {
        jest.spyOn(api, 'get').mockResolvedValue([
            {
                restriction_type: RestrictionType.SKIP_PERSON_PROCESSING,
                distinct_ids: ['user3'],
            },
        ])

        logic.mount()
        logic.values.eventIngestionRestrictions

        await expectLogic(logic)
            .toDispatchActions(['loadEventIngestionRestrictions', 'loadEventIngestionRestrictionsSuccess'])
            .toMatchValues({
                eventIngestionRestrictions: [
                    {
                        restriction_type: RestrictionType.SKIP_PERSON_PROCESSING,
                        distinct_ids: ['user3'],
                    },
                ],
                hasProjectNoticeRestriction: true,
            })
    })

    it('handles FORCE_OVERFLOW_FROM_INGESTION restriction (should not trigger project notice)', async () => {
        jest.spyOn(api, 'get').mockResolvedValue([
            {
                restriction_type: RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
                distinct_ids: ['user4'],
            },
        ])

        logic.mount()
        logic.values.eventIngestionRestrictions

        await expectLogic(logic)
            .toDispatchActions(['loadEventIngestionRestrictions', 'loadEventIngestionRestrictionsSuccess'])
            .toMatchValues({
                eventIngestionRestrictions: [
                    {
                        restriction_type: RestrictionType.FORCE_OVERFLOW_FROM_INGESTION,
                        distinct_ids: ['user4'],
                    },
                ],
                hasProjectNoticeRestriction: false,
            })
    })

    it('handles empty restrictions', async () => {
        jest.spyOn(api, 'get').mockResolvedValue([])

        logic.mount()
        logic.values.eventIngestionRestrictions

        await expectLogic(logic)
            .toDispatchActions(['loadEventIngestionRestrictions', 'loadEventIngestionRestrictionsSuccess'])
            .toMatchValues({
                eventIngestionRestrictions: [],
                hasProjectNoticeRestriction: false,
            })
    })
})
