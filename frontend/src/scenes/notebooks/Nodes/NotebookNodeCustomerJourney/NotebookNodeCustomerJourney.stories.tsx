import { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'
import { useMemo } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { CustomerProfileScope } from '~/types'

import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'

import { notebookTestTemplate } from '../../Notebook/__mocks__/notebook-template-for-snapshot'
import { NotebookType } from '../../types'

const PERSON_ID = '01234567-89ab-cdef-0123-456789abcdef'

const STEP_NAMES = ['Sign up', 'Complete profile', 'First action', 'Activation']

function makeNotebook(shortId: string): NotebookType {
    return {
        ...notebookTestTemplate('Customer Journey Test', [
            {
                type: 'ph-customer-journey',
                attrs: {
                    personId: PERSON_ID,
                    tabId: 'story-tab',
                    nodeId: 'cj-node-1',
                    title: 'Customer journey',
                },
            },
        ]),
        short_id: shortId,
    }
}

function makeFunnelStep(name: string, order: number, count: number): Record<string, unknown> {
    return {
        action_id: name,
        name,
        custom_name: null,
        order,
        count,
        type: 'events',
        average_conversion_time: order > 0 ? 120 : null,
        median_conversion_time: order > 0 ? 90 : null,
        converted_people_url: '/api/person/funnel/?',
        dropped_people_url: order > 0 ? '/api/person/funnel/?' : null,
    }
}

function makeInsight(optionalStepIndices: number[] = []): Record<string, unknown> {
    const series = STEP_NAMES.map((name, i) => ({
        kind: 'EventsNode',
        event: name,
        ...(optionalStepIndices.includes(i) ? { optionalInFunnel: true } : {}),
    }))
    return {
        id: 1,
        short_id: 'insight-1',
        name: 'Onboarding Funnel',
        derived_name: 'Onboarding Funnel',
        description: '',
        deleted: false,
        saved: true,
        query: {
            kind: 'InsightVizNode',
            source: {
                kind: 'FunnelsQuery',
                series,
                funnelsFilter: { funnelVizType: 'flow' },
            },
        },
        result: null,
        created_at: '2024-01-01T00:00:00Z',
        last_modified_at: '2024-01-01T00:00:00Z',
        filters: {},
        order: null,
        color: null,
        layouts: {},
        tags: [],
        dashboards: [],
    }
}

const journeysList = {
    count: 1,
    next: null,
    previous: null,
    results: [
        {
            id: 'journey-1',
            insight: 1,
            name: 'Onboarding Journey',
            description: '',
        },
    ],
}

const notebooksListMock = {
    count: 1,
    next: null,
    previous: null,
    results: [
        {
            id: 'notebook-cj',
            short_id: 'cj-all-completed',
            title: 'Customer Journey Test',
            created_at: '2024-01-01T00:00:00Z',
            last_modified_at: '2024-01-01T00:00:00Z',
        },
    ],
}

const CANVAS_SHORT_ID = `canvas-${PERSON_ID}`

function AppWithProfileContext(): JSX.Element {
    const attrs = useMemo(() => ({ personId: PERSON_ID }), [])
    const profileProps = {
        attrs,
        scope: CustomerProfileScope.PERSON,
        key: `person-${PERSON_ID}`,
        canvasShortId: CANVAS_SHORT_ID,
    }
    return (
        <BindLogic logic={customerProfileLogic} props={profileProps}>
            <App />
        </BindLogic>
    )
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks/Nodes/Customer Journey',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
        featureFlags: [FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS],
    },
    decorators: [
        mswDecorator({
            get: {
                'api/environments/:team_id/customer_journeys/': journeysList,
                'api/environments/:team_id/customer_profile_configs/': { count: 0, results: [] },
                'api/projects/:team_id/notebooks/': notebooksListMock,
                'api/projects/:team_id/notebooks/cj-all-completed/': makeNotebook('cj-all-completed'),
                'api/projects/:team_id/notebooks/cj-some-completed/': makeNotebook('cj-some-completed'),
                'api/projects/:team_id/notebooks/cj-optional-steps/': makeNotebook('cj-optional-steps'),
                'api/projects/:team_id/notebooks/cj-none-completed/': makeNotebook('cj-none-completed'),
            },
        }),
    ],
}
export default meta

export const AllStepsCompleted: StoryFn = () => {
    useStorybookMocks({
        get: { 'api/environments/:team_id/insights/1/': makeInsight() },
        post: {
            'api/environments/:team_id/query/': {
                result: [
                    makeFunnelStep('Sign up', 0, 100),
                    makeFunnelStep('Complete profile', 1, 85),
                    makeFunnelStep('First action', 2, 70),
                    makeFunnelStep('Activation', 3, 55),
                ],
            },
        },
    })
    return <AppWithProfileContext />
}
AllStepsCompleted.parameters = {
    pageUrl: urls.notebook('cj-all-completed'),
    testOptions: { waitForSelector: '.react-flow__node' },
}

export const SomeStepsCompleted: StoryFn = () => {
    useStorybookMocks({
        get: { 'api/environments/:team_id/insights/1/': makeInsight() },
        post: {
            'api/environments/:team_id/query/': {
                result: [
                    makeFunnelStep('Sign up', 0, 1),
                    makeFunnelStep('Complete profile', 1, 1),
                    makeFunnelStep('First action', 2, 0),
                    makeFunnelStep('Activation', 3, 0),
                ],
            },
        },
    })
    return <AppWithProfileContext />
}
SomeStepsCompleted.parameters = {
    pageUrl: urls.notebook('cj-some-completed'),
    testOptions: { waitForSelector: '.react-flow__node' },
}

export const WithOptionalSteps: StoryFn = () => {
    useStorybookMocks({
        get: { 'api/environments/:team_id/insights/1/': makeInsight([1, 3]) },
        post: {
            'api/environments/:team_id/query/': {
                result: [
                    makeFunnelStep('Sign up', 0, 1),
                    makeFunnelStep('Complete profile', 1, 1),
                    makeFunnelStep('First action', 2, 1),
                    makeFunnelStep('Activation', 3, 0),
                ],
            },
        },
    })
    return <AppWithProfileContext />
}
WithOptionalSteps.parameters = {
    pageUrl: urls.notebook('cj-optional-steps'),
    testOptions: { waitForSelector: '.react-flow__node' },
}

export const NoStepsCompleted: StoryFn = () => {
    useStorybookMocks({
        get: { 'api/environments/:team_id/insights/1/': makeInsight() },
        post: {
            'api/environments/:team_id/query/': {
                result: [
                    makeFunnelStep('Sign up', 0, 0),
                    makeFunnelStep('Complete profile', 1, 0),
                    makeFunnelStep('First action', 2, 0),
                    makeFunnelStep('Activation', 3, 0),
                ],
            },
        },
    })
    return <AppWithProfileContext />
}
NoStepsCompleted.parameters = {
    pageUrl: urls.notebook('cj-none-completed'),
    testOptions: { waitForSelector: '.react-flow__node' },
}
