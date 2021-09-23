import { BuiltLogic } from 'kea'
import { eventsTableLogicType } from 'scenes/events/eventsTableLogicType'
import { EventsTableEvent, eventsTableLogic, EventsTableLogicProps } from 'scenes/events/eventsTableLogic'
import { createMemoryHistory } from 'history'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { mockAPI } from 'lib/api.mock'

jest.mock('lib/api')

describe('reading from the url to the action', () => {
    let urlLogic: BuiltLogic<eventsTableLogicType<EventsTableEvent, EventsTableLogicProps>>

    const memoryHistory = createMemoryHistory()
    const urlEncodedProperties =
        '%5B%7B"key"%3A"%24active_feature_flags"%2C"value"%3A"a"%2C"operator"%3A"icontains"%2C"type"%3A"event"%7D%5D'
    const decodedProperties = [
        {
            key: '$active_feature_flags',
            value: 'a',
            operator: 'icontains',
            type: 'event',
        },
    ]
    memoryHistory.push({
        search: `?properties=${urlEncodedProperties}&autoload=true`,
    })

    mockAPI(async () => ({ results: [], count: 0 }))

    initKeaTestLogic({
        logic: eventsTableLogic,
        props: {
            key: 'test-key',
        },
        onLogic: async (l) => {
            urlLogic = l
        },
        memoryHistory,
    })

    it('reads from the URL', async () => {
        await expectLogic(urlLogic).toMatchValues({
            properties: decodedProperties,
            automaticLoadEnabled: true,
        })
    })
})
