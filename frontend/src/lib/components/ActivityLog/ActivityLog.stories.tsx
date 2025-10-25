import { Meta } from '@storybook/react'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import {
    featureFlagsActivityResponseJson,
    insightsActivityResponseJson,
    personActivityResponseJson,
    teamActivityResponseJson,
} from 'lib/components/ActivityLog/__mocks__/activityLogMocks'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import organizationCurrent from '~/mocks/fixtures/api/organizations/@current/@current.json'
import { ActivityScope } from '~/types'

const meta: Meta<typeof ActivityLog> = {
    title: 'Components/ActivityLog',
    component: ActivityLog,
    decorators: [
        mswDecorator({
            get: {
                // TODO: setting available featues should be a decorator to make this easy
                '/api/users/@me': () => [
                    200,
                    {
                        email: 'test@posthog.com',
                        first_name: 'Test Hedgehog',
                        organization: {
                            ...organizationCurrent,
                            available_product_features: [
                                {
                                    key: 'audit_logs',
                                    name: 'Audit logs',
                                },
                            ],
                        },
                    },
                ],
                '/api/projects/:team/feature_flags/6/activity': (_, __, ctx) => [
                    ctx.status(200),
                    ctx.json({ results: [] }),
                ],
                '/api/projects/:team/feature_flags/7/activity': (_, __, ctx) => [
                    ctx.status(200),
                    ctx.json({ results: featureFlagsActivityResponseJson }),
                ],
                '/api/environments/:team_id/insights/activity': (_, __, ctx) => [
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
    parameters: {
        mockDate: '2024-05-01 12:00:00',
    },
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

export function WithoutAuditLogsFeaure(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/users/@me': () => [
                200,
                {
                    email: 'test@posthog.com',
                    first_name: 'Test Hedgehog',
                    organization: {
                        ...organizationCurrent,
                        available_product_features: [],
                    },
                },
            ],
        },
    })
    return <ActivityLog scope={ActivityScope.FEATURE_FLAG} id={7} />
}
