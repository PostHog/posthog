import { Meta } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { Scene } from 'scenes/sceneTypes'
import { useStorybookMocks } from '~/mocks/browser'
import { navigation3000Logic } from '../navigationLogic'
import { Sidebar } from './Sidebar'
import featureFlagsJson from '../../../scenes/feature-flags/__mocks__/feature_flags.json'
import dashboardsJson from '../../../scenes/dashboard/__mocks__/dashboards.json'
import { with3000 } from 'storybook/decorators/with3000'
import { SidebarNavbarItem } from '../types'

export default {
    title: 'PostHog 3000/Sidebar',
    parameters: {
        mockDate: '2023-02-01',
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
    },
    decorators: [with3000],
} as Meta

/** featureFlagsJson * 6 to fill the sidebar up more. */
const multipliedFeatureFlagsJson = {
    ...featureFlagsJson,
    results: featureFlagsJson.results
        .concat(featureFlagsJson.results)
        .concat(featureFlagsJson.results)
        .concat(featureFlagsJson.results)
        .concat(featureFlagsJson.results)
        .concat(featureFlagsJson.results),
    count: featureFlagsJson.results.length * 6,
}

export function Dashboards(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/dashboards/': dashboardsJson,
        },
    })
    const { showSidebar } = useActions(navigation3000Logic)
    const { activeNavbarItem } = useValues(navigation3000Logic)
    useEffect(() => {
        showSidebar(Scene.Dashboards) // Active this sidebar
    }, [])

    return (
        <div className="flex">
            <Sidebar navbarItem={activeNavbarItem as SidebarNavbarItem} />
        </div>
    )
}

export function FeatureFlags(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/feature_flags/': multipliedFeatureFlagsJson,
        },
    })
    const { showSidebar } = useActions(navigation3000Logic)
    const { activeNavbarItem } = useValues(navigation3000Logic)
    useEffect(() => {
        showSidebar(Scene.FeatureFlags) // Activate this sidebar
    }, [])

    return (
        <div className="flex">
            <Sidebar navbarItem={activeNavbarItem as SidebarNavbarItem} />
        </div>
    )
}
