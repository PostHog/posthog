import {
    HistoryActions,
    HistoryListItem,
    historyListLogic,
    HumanizedHistoryListItem,
} from 'lib/components/HistoryList/historyListLogic'
import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { mockAPI } from 'lib/api.mock'
import { dayjs } from 'lib/dayjs'

jest.mock('lib/api')

const aHumanizedPageOfHistory: HumanizedHistoryListItem[] = [
    {
        email: 'kunal@posthog.com',
        name: 'kunal',
        description: 'created the feature flag: test flag',
        created_at: dayjs('2022-02-05T16:28:39.594Z'),
    },
    {
        email: 'eli@posthog.com',
        name: 'eli',
        description: 'added "this is what was added" as the flag description',
        created_at: dayjs('2022-02-06T16:28:39.594Z'),
    },
    {
        email: 'guido@posthog.com',
        name: 'guido',
        description: 'added a filter to the flag',
        created_at: dayjs('2022-02-08T16:28:39.594Z'),
    },
]

const aPageOfHistory: HistoryListItem[] = [
    {
        email: 'kunal@posthog.com',
        name: 'kunal',
        action: HistoryActions.CREATED_FEATURE_FLAG,
        detail: {
            id: 7,
            name: 'test flag',
        },
        created_at: '2022-02-05T16:28:39.594Z',
    },
    {
        email: 'eli@posthog.com',
        name: 'eli',
        action: HistoryActions.ADD_DESCRIPTION_TO_FLAG,
        detail: {
            id: 7,
            description: 'this is what was added',
        },
        created_at: '2022-02-06T16:28:39.594Z',
    },
    {
        email: 'guido@posthog.com',
        name: 'guido',
        action: HistoryActions.ADD_FILTER_TO_FLAG,
        detail: {
            id: 7,
            filter: 'filter info',
        },
        created_at: '2022-02-08T16:28:39.594Z',
    },
]

describe('the history list logic', () => {
    let logic: ReturnType<typeof historyListLogic.build>

    mockAPI(async ({ pathname }) => {
        if (pathname == '/api/projects/@current/feature_flags/7/history') {
            return {
                results: aPageOfHistory,
            }
        }
    })

    beforeEach(() => {
        initKeaTests()
        logic = historyListLogic({ type: 'feature_flags', id: 7 })
        logic.mount()
    })

    it('sets a key', () => {
        expect(logic.key).toEqual('history/feature_flags')
    })

    it('can load a page of history', async () => {
        await expectLogic(logic).toMatchValues({
            isLoading: false,
            history: { 7: aHumanizedPageOfHistory },
        })
    })
})
