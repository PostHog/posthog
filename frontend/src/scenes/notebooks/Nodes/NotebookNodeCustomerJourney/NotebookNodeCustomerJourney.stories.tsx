import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useMemo } from 'react'

import { App } from 'scenes/App'
import {
    JOURNEY_FEATURE_FLAGS,
    journeysList,
    makeInsight,
    allCompletedSteps,
    someCompletedSteps,
    optionalStepResults,
    noCompletedSteps,
} from 'scenes/funnels/FunnelFlowGraph/__mocks__/journeyMocks'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { CustomerProfileScope } from '~/types'

import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'

import { notebookTestTemplate } from '../../Notebook/__mocks__/notebook-template-for-snapshot'
import { NotebookType } from '../../types'

const PERSON_ID = '01234567-89ab-cdef-0123-456789abcdef'

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
        featureFlags: JOURNEY_FEATURE_FLAGS,
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

type Story = StoryObj<{}>

export const AllStepsCompleted: Story = {
    render: () => {
        useStorybookMocks({
            get: { 'api/environments/:team_id/insights/1/': makeInsight() },
            post: { 'api/environments/:team_id/query/': { result: allCompletedSteps() } },
        })
        return <AppWithProfileContext />
    },
    parameters: {
        pageUrl: urls.notebook('cj-all-completed'),
        testOptions: { waitForSelector: '.react-flow__node' },
    },
}

export const SomeStepsCompleted: Story = {
    render: () => {
        useStorybookMocks({
            get: { 'api/environments/:team_id/insights/1/': makeInsight() },
            post: { 'api/environments/:team_id/query/': { result: someCompletedSteps() } },
        })
        return <AppWithProfileContext />
    },
    parameters: {
        pageUrl: urls.notebook('cj-some-completed'),
        testOptions: { waitForSelector: '.react-flow__node' },
    },
}

export const WithOptionalSteps: Story = {
    render: () => {
        useStorybookMocks({
            get: { 'api/environments/:team_id/insights/1/': makeInsight([1, 3]) },
            post: { 'api/environments/:team_id/query/': { result: optionalStepResults() } },
        })
        return <AppWithProfileContext />
    },
    parameters: {
        pageUrl: urls.notebook('cj-optional-steps'),
        testOptions: { waitForSelector: '.react-flow__node' },
    },
}

export const NoStepsCompleted: Story = {
    render: () => {
        useStorybookMocks({
            get: { 'api/environments/:team_id/insights/1/': makeInsight() },
            post: { 'api/environments/:team_id/query/': { result: noCompletedSteps() } },
        })
        return <AppWithProfileContext />
    },
    parameters: {
        pageUrl: urls.notebook('cj-none-completed'),
        testOptions: { waitForSelector: '.react-flow__node' },
    },
}
