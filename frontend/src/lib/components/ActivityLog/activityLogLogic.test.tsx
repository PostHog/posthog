import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { dayjs } from 'lib/dayjs'
import React from 'react'
import { useMocks } from '~/mocks/jest'
import { urls } from 'scenes/urls'
import { Link } from 'lib/components/Link'
import {
    ActivityScope,
    HumanizedActivityLogItem,
    registerActivityDescriptions,
} from 'lib/components/ActivityLog/humanizeActivity'
import { activityLogLogic } from 'lib/components/ActivityLog/activityLogLogic'
import { featureFlagsActivityResponseJson } from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'

const aHumanizedPageOfHistory: HumanizedActivityLogItem[] = [
    {
        email: 'kunal@posthog.com',
        name: 'kunal',
        description: (
            <>
                created the flag: <Link to={urls.featureFlag('7')}>test flag</Link>
            </>
        ),
        created_at: dayjs('2022-02-05T16:28:39.594Z'),
    },
    {
        email: 'eli@posthog.com',
        name: 'eli',
        description: expect.anything(), // react fragment equality is odd here. tested in humanizeActivity.test.tsx
        created_at: dayjs('2022-02-06T16:28:39.594Z'),
    },
    {
        email: 'guido@posthog.com',
        name: 'guido',
        description: expect.anything(), // react fragment equality is odd here. tested in humanizeActivity.test.tsx
        created_at: dayjs('2022-02-08T16:28:39.594Z'),
    },
]

describe('the activity log logic', () => {
    let logic: ReturnType<typeof activityLogLogic.build>
    registerActivityDescriptions({ scope: ActivityScope.FEATURE_FLAG, describer: flagActivityDescriber })

    describe('when not scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/activity/': { results: featureFlagsActivityResponseJson },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: 'FeatureFlag' })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/FeatureFlag/all')
        })

        it('can load a page of history', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchActivity()
            })
                .toFinishAllListeners()
                .toMatchValues({
                    activityLoading: false,
                    activity: aHumanizedPageOfHistory,
                })
        })
    })
    describe('when scoped by ID', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/@current/feature_flags/7/activity/': { results: featureFlagsActivityResponseJson },
                },
            })
            initKeaTests()
            logic = activityLogLogic({ scope: 'FeatureFlag', id: 7 })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('activity/FeatureFlag/7')
        })

        it('can load a page of history', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchActivity()
            })
                .toFinishAllListeners()
                .toMatchValues({
                    activityLoading: false,
                    activity: aHumanizedPageOfHistory,
                })
        })
    })
})
