import React from 'react'
import { featureFlagsActivityResponseJson } from 'lib/components/ActivityLog/__mocks__/activityLogMocks'
import { mswDecorator } from '~/mocks/browser'
import { ComponentMeta } from '@storybook/react'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { flagActivityDescriber } from 'scenes/feature-flags/activityDescriptions'

export default {
    title: 'Components/ActivityLog',
    component: ActivityLog,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/@current/feature_flags/5/activity': (_, __, ctx) => [
                    ctx.delay(86400000),
                    ctx.status(200),
                    ctx.json({ results: [] }),
                ],
                '/api/projects/@current/feature_flags/6/activity': (_, __, ctx) => [
                    ctx.delay(1000),
                    ctx.status(200),
                    ctx.json({ results: [] }),
                ],
                '/api/projects/@current/feature_flags/7/activity': (_, __, ctx) => [
                    ctx.delay(1000),
                    ctx.status(200),
                    ctx.json({ results: featureFlagsActivityResponseJson }),
                ],
            },
        }),
    ],
} as ComponentMeta<typeof ActivityLog>

export function WithData(): JSX.Element {
    return <ActivityLog scope={'FeatureFlag'} id={7} describer={flagActivityDescriber} />
}

export function WithNoData(): JSX.Element {
    return <ActivityLog scope={'FeatureFlag'} id={6} describer={flagActivityDescriber} />
}

export function Timeout(): JSX.Element {
    return <ActivityLog scope={'FeatureFlag'} id={5} describer={flagActivityDescriber} />
}
