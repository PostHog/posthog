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
import React from 'react'

jest.mock('lib/api')

const aHumanizedPageOfHistory: HumanizedHistoryListItem[] = [
    {
        email: 'kunal@posthog.com',
        name: 'kunal',
        description: 'created the flag',
        created_at: dayjs('2022-02-05T16:28:39.594Z'),
    },
    {
        email: 'eli@posthog.com',
        name: 'eli',
        description: 'changed the description of the flag to: this is what was added',
        created_at: dayjs('2022-02-06T16:28:39.594Z'),
    },
    {
        email: 'guido@posthog.com',
        name: 'guido',
        description: (
            <>
                changed the filters to <pre>{JSON.stringify({ filter: 'info' })}</pre>
            </>
        ),
        created_at: dayjs('2022-02-08T16:28:39.594Z'),
    },
]

const aPageOfHistory: HistoryListItem[] = [
    {
        email: 'kunal@posthog.com',
        name: 'kunal',
        action: HistoryActions.FEATURE_FLAG_CREATED,
        detail: {
            id: 7,
            name: 'test flag',
        },
        created_at: '2022-02-05T16:28:39.594Z',
    },
    {
        email: 'eli@posthog.com',
        name: 'eli',
        action: HistoryActions.FEATURE_FLAG_DESCRIPTION_CHANGED,
        detail: {
            id: 7,
            to: 'this is what was added',
        },
        created_at: '2022-02-06T16:28:39.594Z',
    },
    {
        email: 'guido@posthog.com',
        name: 'guido',
        action: HistoryActions.FEATURE_FLAG_FILTERS_CHANGED,
        detail: {
            id: 7,
            to: { filter: 'info' },
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
        logic = historyListLogic({ type: 'FeatureFlag', id: 7 })
        logic.mount()
    })

    it('sets a key', () => {
        expect(logic.key).toEqual('history/FeatureFlag/7')
    })

    it('can load a page of history', async () => {
        await expectLogic(logic).toMatchValues({
            historyLoading: false,
            history: aHumanizedPageOfHistory,
        })
    })
})
