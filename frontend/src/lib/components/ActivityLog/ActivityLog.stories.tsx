import {
    featureFlagsActivityResponseJson,
    insightsActivityResponseJson,
    personActivityResponseJson,
} from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { mswDecorator } from '~/mocks/browser'
import { ComponentMeta } from '@storybook/react'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'

export default {
    title: 'Components/ActivityLog',
    component: ActivityLog,
    parameters: { testOptions: { skip: true } }, // FIXME: Currently disabled as the Timeout story is flaky
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/feature_flags/5/activity': (_, __, ctx) => [
                    ctx.delay(86400000),
                    ctx.status(200),
                    ctx.json({ results: [] }),
                ],
                '/api/projects/:team/feature_flags/6/activity': (_, __, ctx) => [
                    ctx.status(200),
                    ctx.json({ results: [] }),
                ],
                '/api/projects/:team/feature_flags/7/activity': (_, __, ctx) => [
                    ctx.status(200),
                    ctx.json({ results: featureFlagsActivityResponseJson }),
                ],
                '/api/projects/:team/insights/activity': (_, __, ctx) => [
                    ctx.status(200),
                    ctx.json({ results: insightsActivityResponseJson }),
                ],
                '/api/person/:id/activity': (_, __, ctx) => [
                    ctx.status(200),
                    ctx.json({ results: personActivityResponseJson }),
                ],
            },
        }),
    ],
} as ComponentMeta<typeof ActivityLog>

export function FeatureFlagActivity(): JSX.Element {
    return <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={7} />
}

export function InsightActivity(): JSX.Element {
    return <ActivityLog scope={ActivityScope.INSIGHT} />
}

export function PersonsActivity(): JSX.Element {
    return <ActivityLog scope={ActivityScope.PERSON} id={12} />
}

export function WithCaption(): JSX.Element {
    return (
        <ActivityLog
            scope={ActivityScope.FEATURE_FLAG}
            id={7}
            caption={
                <>
                    This is a list that <strong>needs</strong> some extra description or context. Which can have a very,
                    very long caption. A <i>very</i> long caption that wraps over more than one line, not a very
                    Hemingway choice, but important information has to be included. And it will be, in this prop.
                </>
            }
        />
    )
}

export function WithNoData(): JSX.Element {
    return <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={6} />
}

export function Timeout(): JSX.Element {
    return <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={5} />
}
