import {
    ActivityChange,
    ActivityLogItem,
    ActivityScope,
    humanize,
    registerActivityDescriptions,
} from 'lib/components/ActivityLog/humanizeActivity'
import { render } from '@testing-library/react'
import { dayjs } from 'lib/dayjs'
import React from 'react'
import '@testing-library/jest-dom'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'

const makeAPIItem = (name: string, activity: string, changes: ActivityChange[] | null = null): ActivityLogItem => ({
    user: { first_name: 'kunal', email: 'kunal@posthog.com' },
    activity,
    scope: ActivityScope.FEATURE_FLAG,
    item_id: '7',
    detail: {
        changes: changes,
        name,
    },
    created_at: '2022-02-05T16:28:39.594Z',
})

describe('humanizing the activity log', () => {
    describe('humanizing feature flags', () => {
        registerActivityDescriptions({ scope: ActivityScope.FEATURE_FLAG, describer: flagActivityDescriber })

        it('can handle creation', () => {
            const apiItem = makeAPIItem('test created flag', 'created')
            const actual = humanize([apiItem])
            expect(actual).toEqual([
                {
                    email: 'kunal@posthog.com',
                    name: 'kunal',
                    description: expect.anything(),
                    created_at: dayjs('2022-02-05T16:28:39.594Z'),
                },
            ])

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'created the flag: test created flag'
            )
        })
        it('can handle deletion', () => {
            const apiItem = makeAPIItem('test del flag', 'deleted')
            const actual = humanize([apiItem])
            expect(actual).toEqual([
                {
                    email: 'kunal@posthog.com',
                    name: 'kunal',
                    description: expect.anything(),
                    created_at: dayjs('2022-02-05T16:28:39.594Z'),
                },
            ])

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('deleted the flag: test del flag')
        })
        it('can handle soft deletion', () => {
            const apiItem = makeAPIItem('test flag', 'updated', [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'deleted',
                    after: true,
                },
            ])
            const actual = humanize([apiItem])
            expect(actual).toEqual([
                {
                    email: 'kunal@posthog.com',
                    name: 'kunal',
                    description: expect.anything(),
                    created_at: dayjs('2022-02-05T16:28:39.594Z'),
                },
            ])

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent('deleted the flag: test flag')
        })
        it('can handle name change', () => {
            const apiItem = makeAPIItem('test flag', 'updated', [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'name',
                    before: 'potato',
                    after: 'tomato',
                },
            ])
            const actual = humanize([apiItem])
            expect(actual).toEqual([
                {
                    email: 'kunal@posthog.com',
                    name: 'kunal',
                    description: expect.anything(),
                    created_at: dayjs('2022-02-05T16:28:39.594Z'),
                },
            ])

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'changed the description to "tomato" on test flag'
            )
        })

        it('can handle rollout percentage change', () => {
            const apiItem = makeAPIItem('test flag', 'updated', [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'rollout_percentage',
                    after: '36',
                },
            ])
            const actual = humanize([apiItem])
            expect(actual).toEqual([
                {
                    email: 'kunal@posthog.com',
                    name: 'kunal',
                    description: expect.anything(),
                    created_at: dayjs('2022-02-05T16:28:39.594Z'),
                },
            ])

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'changed rollout percentage to 36% on test flag'
            )
        })

        it('can humanize more than one change', () => {
            const apiItem = makeAPIItem('test flag', 'updated', [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'rollout_percentage',
                    after: '36',
                },
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'name',
                    after: 'strawberry',
                },
            ])
            const actual = humanize([apiItem])
            expect(actual).toEqual([
                {
                    email: 'kunal@posthog.com',
                    name: 'kunal',
                    description: expect.anything(),
                    created_at: dayjs('2022-02-05T16:28:39.594Z'),
                },
                {
                    email: 'kunal@posthog.com',
                    name: 'kunal',
                    description: expect.anything(),
                    created_at: dayjs('2022-02-05T16:28:39.594Z'),
                },
            ])

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'changed rollout percentage to 36% on test flag'
            )
            expect(render(<>{actual[1].description}</>).container).toHaveTextContent(
                'changed the description to "strawberry" on test flag'
            )
        })

        it('can handle filter change - boolean value, no conditions', () => {
            const apiItem = makeAPIItem('test flag', 'updated', [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'filters',
                    after: { groups: [{ properties: [], rollout_percentage: 99 }], multivariate: null },
                },
            ])
            const actual = humanize([apiItem])
            expect(actual).toEqual([
                {
                    email: 'kunal@posthog.com',
                    name: 'kunal',
                    description: expect.anything(),
                    created_at: dayjs('2022-02-05T16:28:39.594Z'),
                },
            ])

            expect(render(<>{actual[0].description}</>).container).toHaveTextContent(
                'changed the rollout percentage to 99% of all users on test flag'
            )
        })
    })
})
