import { Meta, StoryFn } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import {
    allCompletedSteps,
    JOURNEY_FEATURE_FLAGS,
    journeysList,
    makeInsight,
    optionalStepResults,
    someCompletedSteps,
} from './__mocks__/journeyMocks'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Customer Analytics/Journeys',
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
            },
        }),
    ],
}
export default meta

export const JourneyWithRequiredSteps: StoryFn = () => {
    useStorybookMocks({
        get: { 'api/environments/:team_id/insights/1/': makeInsight() },
        post: { 'api/environments/:team_id/query/': { result: allCompletedSteps() } },
    })
    return <App />
}
JourneyWithRequiredSteps.parameters = {
    pageUrl: urls.customerAnalyticsJourneys(),
    testOptions: { waitForSelector: '.react-flow__node' },
}

export const JourneyWithEmptySteps: StoryFn = () => {
    useStorybookMocks({
        get: { 'api/environments/:team_id/insights/1/': makeInsight() },
        post: { 'api/environments/:team_id/query/': { result: someCompletedSteps() } },
    })
    return <App />
}
JourneyWithEmptySteps.parameters = {
    pageUrl: urls.customerAnalyticsJourneys(),
    testOptions: { waitForSelector: '.react-flow__node' },
}

export const JourneyWithOptionalSteps: StoryFn = () => {
    useStorybookMocks({
        get: { 'api/environments/:team_id/insights/1/': makeInsight([1, 3]) },
        post: { 'api/environments/:team_id/query/': { result: optionalStepResults() } },
    })
    return <App />
}
JourneyWithOptionalSteps.parameters = {
    pageUrl: urls.customerAnalyticsJourneys(),
    testOptions: { waitForSelector: '.react-flow__node' },
}
