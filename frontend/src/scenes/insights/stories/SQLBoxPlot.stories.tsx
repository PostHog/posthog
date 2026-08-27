import { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { useEffect, useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import __sqlBoxPlot from '../../../mocks/fixtures/api/projects/team_id/insights/sqlBoxPlot.json'

const availableSources = {
    Postgres: { name: 'Postgres', iconPath: '/static/services/postgres.png', fields: [], caption: '', featured: true },
    Stripe: { name: 'Stripe', iconPath: '/static/services/stripe.png', fields: [], caption: '', featured: true },
    GoogleAds: {
        name: 'GoogleAds',
        iconPath: '/static/services/google-ads.png',
        fields: [],
        caption: '',
        featured: true,
    },
}

type Story = StoryObj<{}>

const grantWarehouseAccess: Decorator = function GrantWarehouseAccess(Story): JSX.Element {
    const appContext = (window as any).POSTHOG_APP_CONTEXT
    const originalAccess = useRef<unknown>()
    if (appContext && originalAccess.current === undefined) {
        originalAccess.current = appContext.resource_access_control
        appContext.resource_access_control = {
            ...appContext.resource_access_control,
            [AccessControlResourceType.WarehouseObjects]: AccessControlLevel.Editor,
        }
    }
    useEffect(
        () => () => {
            if (appContext) {
                appContext.resource_access_control = originalAccess.current
            }
        },
        [appContext]
    )
    return <Story />
}

const meta: Meta = {
    title: 'Scenes-App/Insights/SQLBoxPlot',
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.SQL_BOX_PLOT_INSIGHT],
        testOptions: {
            snapshotBrowsers: ['chromium'],
            viewport: { width: 1300, height: 720 },
            waitForSelector: '[data-attr="sql-box-plot"]',
        },
        viewMode: 'story',
        mockDate: '2026-02-02',
    },
    decorators: [
        grantWarehouseAccess,
        mswDecorator({
            get: {
                '/api/projects/:team_id/groups_types': [],
                '/api/projects/:team_id/query_tab_state/user': () => [200, null],
                '/api/projects/:team_id/external_data_sources/connections': [],
                '/api/projects/:team_id/external_data_sources/direct_connection_options': [],
                '/api/environments/:team_id/external_data_sources/wizard': availableSources,
            },
        }),
    ],
}

export default meta

export const GroupedSeries: Story = createInsightStory(__sqlBoxPlot as any)

export const EditOptions: Story = {
    render: createInsightStory(__sqlBoxPlot as any, 'edit'),
    parameters: {
        ...meta.parameters,
        testOptions: {
            ...meta.parameters?.testOptions,
            waitForSelector: '[data-attr="box-plot-minColumn"]',
        },
    },
    play: async ({ canvasElement }): Promise<void> => {
        await waitFor(
            async () => {
                if (canvasElement.querySelector('[data-attr="box-plot-minColumn"]')) {
                    return
                }
                const settingsButton = canvasElement.querySelector<HTMLElement>(
                    '[data-attr="sql-editor-visualization-settings-button"]'
                )
                if (!settingsButton) {
                    throw new Error('Visualization settings button not ready')
                }
                await userEvent.click(settingsButton)
                if (!canvasElement.querySelector('[data-attr="box-plot-minColumn"]')) {
                    throw new Error('Box plot settings not ready')
                }
            },
            { timeout: 10_000 }
        )
    },
}
