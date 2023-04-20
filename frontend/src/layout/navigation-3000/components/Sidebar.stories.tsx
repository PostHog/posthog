import { Meta } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'
import { Scene } from 'scenes/sceneTypes'
import { useStorybookMocks } from '~/mocks/browser'
import { navigation3000Logic } from '../navigationLogic'
import { themeLogic } from '../themeLogic'
import { Sidebar } from './Sidebar'

export default {
    title: 'PostHog 3000/Sidebar',
    parameters: {
        mockDate: '2023-02-01',
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
    },
} as Meta

export function Dashboards(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/dashboards/': require('../../../scenes/dashboard/__mocks__/dashboards.json'),
        },
    })
    const { showSidebar } = useActions(navigation3000Logic)
    useMountedLogic(themeLogic)
    useEffect(() => {
        showSidebar(Scene.Dashboards) // Active this sidebar
    }, [])

    return (
        <div className="flex">
            <Sidebar />
        </div>
    )
}

export function FeatureFlags(): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/feature_flags/': require('../../../scenes/feature-flags/__mocks__/feature_flags.json'),
        },
    })
    const { showSidebar } = useActions(navigation3000Logic)
    useMountedLogic(themeLogic)
    useEffect(() => {
        showSidebar(Scene.FeatureFlags) // Activate this sidebar
    }, [])

    return (
        <div className="flex">
            <Sidebar />
        </div>
    )
}
