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

    it('writes autoload toggle to the URL', async () => {
        await expectLogic(urlLogic, () => {
            urlLogic.actions.toggleAutomaticLoad(true)
        })
        expect(memoryHistory.location.search).toContain('autoload=true')
    })
})
