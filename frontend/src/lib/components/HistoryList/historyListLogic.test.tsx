import {
    HistoryActions,
    HistoryListItem,
    historyListLogic,
    HumanizedHistoryListItem,
} from 'lib/components/HistoryList/historyListLogic'
import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { dayjs } from 'lib/dayjs'
import React from 'react'
import { useMocks } from '~/mocks/jest'

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
                changed the filters to <code>{JSON.stringify({ filter: 'info' })}</code>
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

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/@current/feature_flags/7/history/': { results: aPageOfHistory },
            },
        })
        initKeaTests()
        logic = historyListLogic({ type: 'FeatureFlag', id: 7 })
        logic.mount()
    })

    it('sets a key', () => {
        expect(logic.key).toEqual('history/FeatureFlag/7')
    })

    it.only('can load a page of history', async () => {
        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            historyLoading: false,
            history: aHumanizedPageOfHistory,
        })
    })
})
