import { Meta } from '@storybook/react'
import {
    featureFlagsActivityResponseJson,
    insightsActivityResponseJson,
    personActivityResponseJson,
    teamActivityResponseJson,
} from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'

import { mswDecorator } from '~/mocks/browser'
import { ActivityScope } from '~/types'

const meta: Meta<typeof ActivityLog> = {
    title: 'Components/ActivityLog',
    component: ActivityLog,
    tags: ['test-skip'], // FIXME: Currently disabled as the Timeout story is flaky
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
                '/api/projects/:id/activity': (_, __, ctx) => [
                    ctx.status(200),
                    ctx.json({ results: teamActivityResponseJson }),
                ],
            },
        }),
    ],
}
export default meta

export function FeatureFlagActivity(): JSX.Element {
    return <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={7} />
}

export function DataManagementActivity(): JSX.Element {
    return <ActivityLog scope={ActivityScope.DATA_MANAGEMENT} />
}

export function InsightActivity(): JSX.Element {
    return <ActivityLog scope={ActivityScope.INSIGHT} />
}

export function PersonsActivity(): JSX.Element {
    return <ActivityLog scope={ActivityScope.PERSON} id={12} />
}

export function TeamActivity(): JSX.Element {
    return <ActivityLog scope={ActivityScope.TEAM} id={12} />
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
