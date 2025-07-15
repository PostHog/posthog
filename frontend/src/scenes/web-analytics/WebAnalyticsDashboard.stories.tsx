import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import uniqueVisitorsMock from './__mocks__/UniqueVisitors.json'
import webOverviewMock from './__mocks__/WebOverview.json'
import browserMock from './tiles/__mocks__/Browser.json'
import pathMock from './tiles/__mocks__/Path.json'
import referringDomainMock from './tiles/__mocks__/ReferringDomain.json'
import retentionMock from './tiles/__mocks__/Retention.json'
import { DeviceTab, SourceTab, webAnalyticsLogic } from './webAnalyticsLogic'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Web Analytics',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.webAnalytics(),
        testOptions: {
            includeNavigationInSnapshot: true,
            waitForLoadersToDisappear: true,
            waitForSelector: '[data-attr=trend-line-graph] > canvas',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                // Live count of users on product
                '/stats': () => [200, { users_on_product: 2387 }],

                // Avoid displaying error of missing $pageview/$pageleave/$web_vitals events
                '/api/projects/:team_id/event_definitions': () => [200, { count: 5 }],
            },
            post: {
                '/api/environments/:team_id/query': (req) => {
                    const query = (req.body as any).query
                    const queryKind = query.kind

                    if (queryKind === 'DatabaseSchemaQuery') {
                        return [200, { tables: {} }] // Empty schema, we don't care about this here
                    } else if (queryKind === 'WebOverviewQuery') {
                        return [200, webOverviewMock]
                    } else if (queryKind === 'TrendsQuery') {
                        return [200, uniqueVisitorsMock]
                    } else if (queryKind === 'WebStatsTableQuery') {
                        if (query.breakdownBy === 'Page') {
                            return [200, pathMock]
                        } else if (query.breakdownBy === 'InitialReferringDomain') {
                            return [200, referringDomainMock]
                        } else if (query.breakdownBy === 'Browser') {
                            return [200, browserMock]
                        }
                    } else if (queryKind === 'RetentionQuery') {
                        return [200, retentionMock]
                    }
                },
            },
        }),
    ],
}
export default meta

export function WebAnalyticsDashboard(): JSX.Element {
    const { setSourceTab, setDeviceTab } = useActions(webAnalyticsLogic)

    useEffect(() => {
        // Set the source tab to referring domain
        setSourceTab(SourceTab.REFERRING_DOMAIN)

        // Set the device tab to browsers
        setDeviceTab(DeviceTab.BROWSER)
    }, [setDeviceTab, setSourceTab])

    return <App />
}
