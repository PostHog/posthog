import '~/styles'
import '~/toolbar/styles.scss'

import { Meta } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import { ToolbarApp } from '~/toolbar/ToolbarApp'
import { ToolbarParams } from '~/types'

import { listActionsAPIResponse } from './__mocks__/list-actions-response'
import { listHeatmapStatsAPIResponse } from './__mocks__/list-heatmap-stats-response'
import { listMyFlagsAPIResponse } from './__mocks__/list-my-flags-response'
import { MenuState, toolbarLogic } from './bar/toolbarLogic'
import { toolbarConfigLogic } from './toolbarConfigLogic'

function useToolbarStyles(): void {
    useEffect(() => {
        const head = document.getElementsByTagName('head')[0]
        const shadowRoot = window.document.getElementById('__POSTHOG_TOOLBAR__')?.shadowRoot
        const styleTags: HTMLStyleElement[] = Array.from(head.getElementsByTagName('style'))
        styleTags.forEach((tag) => {
            const style = document.createElement('style')
            const text = tag.innerText
            style.appendChild(document.createTextNode(text))
            shadowRoot?.appendChild(style)
        })
    }, [])
}

const meta: Meta = {
    title: 'Scenes-Other/Toolbar',
    tags: ['test-skip-webkit'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type ToolbarStoryProps = {
    menu?: MenuState
    minimized?: boolean
    unauthenticated?: boolean
    theme?: 'light' | 'dark'
}

const BasicTemplate = (props: ToolbarStoryProps): JSX.Element => {
    const toolbarParams: ToolbarParams = {
        temporaryToken: props.unauthenticated ? undefined : 'UExb1dCsoqBtrhrZYxzmxXQ7XdjVH5Ea_zbQjTFuJqk',
        actionId: undefined,
        userIntent: undefined,
        dataAttributes: ['data-attr'],
        apiURL: '/',
        jsURL: 'http://localhost:8234/',
        userEmail: 'foobar@posthog.com',
    }
    useToolbarStyles()

    useStorybookMocks({
        get: {
            '/decide': {
                config: {
                    enable_collect_everything: true,
                },
                toolbarParams: {
                    toolbarVersion: 'toolbar',
                    jsURL: 'http://localhost:8234/',
                },
                isAuthenticated: props.unauthenticated ?? true,
                supportedCompression: ['gzip', 'gzip-js', 'lz64'],
                featureFlags: {},
                sessionRecording: {
                    endpoint: '/s/',
                },
            },
            '/api/element/stats/': listHeatmapStatsAPIResponse,
            '/api/projects/@current/feature_flags/my_flags': listMyFlagsAPIResponse,
            '/api/projects/@current/actions/': listActionsAPIResponse,
        },
    })

    useMountedLogic(toolbarConfigLogic(toolbarParams))
    const theToolbarLogic = toolbarLogic()

    const { setVisibleMenu, setDragPosition, toggleMinimized, toggleTheme } = useActions(theToolbarLogic)

    useEffect(() => {
        setDragPosition(50, 50)
        setVisibleMenu(props.menu || 'none')
        toggleMinimized(props.minimized ?? false)
        toggleTheme(props.theme || 'light')
    }, [Object.values(props)])

    return (
        <div>
            <div>The toolbar should show up now! Click it to open.</div>
            <button>Click Me</button>
            <ToolbarApp {...toolbarParams} disableExternalStyles />
        </div>
    )
}

export const Default = (): JSX.Element => {
    return <BasicTemplate />
}

export const Unauthenticated = (): JSX.Element => {
    return <BasicTemplate unauthenticated />
}

export const Minimized = (): JSX.Element => {
    return <BasicTemplate minimized />
}

export const Heatmap = (): JSX.Element => {
    return <BasicTemplate menu="heatmap" />
}

export const Inspect = (): JSX.Element => {
    return <BasicTemplate menu="inspect" />
}

export const Actions = (): JSX.Element => {
    return <BasicTemplate menu="actions" />
}

export const FeatureFlags = (): JSX.Element => {
    return <BasicTemplate menu="flags" />
}

// Dark theme
export const DefaultDark = (): JSX.Element => {
    return <BasicTemplate theme="dark" />
}

export const MinimizedDark = (): JSX.Element => {
    return <BasicTemplate theme="dark" minimized />
}

export const HeatmapDark = (): JSX.Element => {
    return <BasicTemplate theme="dark" menu="heatmap" />
}

export const InspectDark = (): JSX.Element => {
    return <BasicTemplate theme="dark" menu="inspect" />
}

export const ActionsDark = (): JSX.Element => {
    return <BasicTemplate theme="dark" menu="actions" />
}

export const FeatureFlagsDark = (): JSX.Element => {
    return <BasicTemplate theme="dark" menu="flags" />
}
