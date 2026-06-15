import { Meta, StoryObj, type Decorator } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { mswDecorator } from '~/mocks/browser'

/**
 * On mobile (viewport < 992px) the project nav becomes a slide-in drawer toggled by a
 * floating button pinned to the top-left. These stories render the full `App` at a phone
 * width with the drawer expanded so we capture the nav header: the account menu trigger
 * has to clear the floating toggle, which previously overlapped it and swallowed taps on
 * the org logo.
 */
const withExpandedMobileNav: Decorator = (Story) => {
    const { showLayoutNavBar } = useActions(panelLayoutLogic)
    // The initial urlToAction closes the drawer on mobile, so open it after mount to make
    // the expanded state stick for the snapshot.
    useEffect(() => {
        showLayoutNavBar(true)
    }, [showLayoutNavBar])
    return <Story />
}

const meta: Meta = {
    component: App,
    title: 'Layout/Mobile Navigation',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.dashboards(),
        testOptions: {
            includeNavigationInSnapshot: true,
            viewport: { width: 414, height: 896 },
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/dashboard_templates/': {},
                '/api/projects/:id/integrations': { results: [] },
                '/api/organizations/:organization_id/pipeline_destinations/': { results: [] },
                '/api/projects/:id/pipeline_destination_configs/': { results: [] },
                '/api/projects/:id/batch_exports/': { results: [] },
                '/api/projects/:id/surveys/': { results: [] },
                '/api/projects/:id/surveys/responses_count/': { results: [] },
                '/api/environments/:team_id/exports/': { results: [] },
                '/api/environments/:team_id/events': { results: [] },
            },
            post: {
                '/api/environments/:team_id/query/:kind': {},
            },
        }),
        withExpandedMobileNav,
    ],
}
export default meta

type Story = StoryObj

export const ExpandedDrawer: Story = {}
