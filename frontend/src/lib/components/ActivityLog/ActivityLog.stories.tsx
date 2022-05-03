import React from 'react'
import {
    featureFlagsActivityResponseJson,
    insightsActivityResponseJson,
} from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { mswDecorator } from '~/mocks/browser'
import { ComponentMeta } from '@storybook/react'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { insightActivityDescriber } from 'scenes/saved-insights/activityDescriptions'

export default {
    title: 'Components/ActivityLog',
    component: ActivityLog,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/feature_flags/5/activity': (_, __, ctx) => [
                    ctx.delay(86400000),
                    ctx.status(200),
                    ctx.json({ results: [] }),
                ],
                '/api/projects/:team/feature_flags/6/activity': (_, __, ctx) => [
                    ctx.delay(1000),
                    ctx.status(200),
                    ctx.json({ results: [] }),
                ],
                '/api/projects/:team/feature_flags/7/activity': (_, __, ctx) => [
                    ctx.delay(1000),
                    ctx.status(200),
                    ctx.json({ results: featureFlagsActivityResponseJson }),
                ],
                '/api/projects/:team/insights/activity': (_, __, ctx) => [
                    ctx.delay(1000),
                    ctx.status(200),
                    ctx.json({ results: insightsActivityResponseJson }),
                ],
            },
        }),
    ],
} as ComponentMeta<typeof ActivityLog>

export function FeatureFlagActivity(): JSX.Element {
    return <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={7} describer={flagActivityDescriber} />
}

export function InsightActivity(): JSX.Element {
    return <ActivityLog scope={ActivityScope.INSIGHT} describer={insightActivityDescriber} />
}

export function WithCaption(): JSX.Element {
    return (
        <ActivityLog
            scope={ActivityScope.FEATURE_FLAG}
            id={7}
            describer={flagActivityDescriber}
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
    return <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={6} describer={flagActivityDescriber} />
}

export function Timeout(): JSX.Element {
    return <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={5} describer={flagActivityDescriber} />
}
