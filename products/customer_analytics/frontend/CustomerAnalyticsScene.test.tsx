import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import type { ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { emptySceneParams } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { initKeaTests } from '~/test/init'

import { CustomerAnalyticsScene } from './CustomerAnalyticsScene'
import { customerAnalyticsSceneLogic } from './customerAnalyticsSceneLogic'

jest.mock('~/layout/scenes/components/FeaturePreviewSceneGate', () => ({
    FeaturePreviewSceneGate: ({ children }: { children: ReactNode }) => <>{children}</>,
}))
jest.mock('~/layout/scenes/components/SceneContent', () => ({
    SceneContent: ({ children }: { children: ReactNode }) => <>{children}</>,
}))
jest.mock('~/layout/scenes/components/SceneTitleSection', () => ({
    SceneTitleSection: ({ name, description }: { name: string; description?: string }) => (
        <>
            <h1>{name}</h1>
            {description && <p>{description}</p>}
        </>
    ),
}))
jest.mock('lib/components/NotFound', () => ({
    NotFound: () => <div data-attr="page-not-found" />,
}))
jest.mock('./CustomerAnalyticsFilters', () => ({ CustomerAnalyticsFilters: () => null }))
jest.mock('./components/AccountNotes/AccountNotesTabContent', () => ({ AccountNotesTabContent: () => null }))
jest.mock('./components/Accounts/AccountsTabContent', () => ({ AccountsTabContent: () => null }))
jest.mock('./components/Announcements/AnnouncementsTabContent', () => ({ AnnouncementsTabContent: () => null }))
jest.mock('./components/CustomerJourneys/CustomerJourneys', () => ({ CustomerJourneys: () => null }))
jest.mock('./components/CustomerJourneys/CustomerJourneySelect', () => ({ CustomerJourneySelect: () => null }))
jest.mock('./components/CustomerJourneys/DeleteJourneyButton', () => ({ DeleteJourneyButton: () => null }))
jest.mock('./components/CustomerTasks/CustomerTasksInbox', () => ({
    CustomerTasksInbox: () => <div data-attr="tasks-inbox" />,
}))
jest.mock('./components/FeatureRequests/FeatureRequestsTabContent', () => ({ FeatureRequestsTabContent: () => null }))
jest.mock('./components/Feed/FeedTabContent', () => ({ FeedTabContent: () => null }))
jest.mock('./components/FeedbackButton', () => ({ FeedbackButton: () => null }))
jest.mock('./components/Insights/ActiveUsersInsights', () => ({ ActiveUsersInsights: () => null }))
jest.mock('./components/Insights/SessionInsights', () => ({ SessionInsights: () => null }))
jest.mock('./components/Insights/SignupInsights', () => ({ SignupInsights: () => null }))

describe('CustomerAnalyticsScene', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        sceneLogic.mount()
        customerAnalyticsSceneLogic.mount()
        sceneLogic.actions.setScene(Scene.CustomerAnalytics, 'customerAnalyticsTasks', emptySceneParams)
    })

    afterEach(() => {
        cleanup()
        customerAnalyticsSceneLogic.unmount()
        sceneLogic.unmount()
        featureFlagLogic.unmount()
    })

    it('shows the Tasks tab and inbox only when the tasks flag is enabled', () => {
        featureFlagLogic.actions.setFeatureFlags(
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS, FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS],
            {
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true,
                [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]: true,
            }
        )

        const { rerender } = render(
            <Provider>
                <CustomerAnalyticsScene />
            </Provider>
        )

        expect(screen.getAllByText('Tasks')).toHaveLength(2)
        expect(document.querySelector('[data-attr="tasks-inbox"]')).toBeInTheDocument()

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.CUSTOMER_ANALYTICS], {
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true,
        })
        rerender(
            <Provider>
                <CustomerAnalyticsScene />
            </Provider>
        )

        expect(document.querySelector('[data-attr="page-not-found"]')).toBeInTheDocument()
    })
})
