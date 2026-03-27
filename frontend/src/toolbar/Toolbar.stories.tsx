import '~/styles'
import '~/toolbar/styles.scss'

import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { useStorybookMocks } from '~/mocks/browser'
import { ToolbarApp } from '~/toolbar/ToolbarApp'
import { ToolbarParams } from '~/types'

import { listActionsAPIResponse } from './__mocks__/list-actions-response'
import { listHeatmapStatsAPIResponse } from './__mocks__/list-heatmap-stats-response'
import { listMyFlagsAPIResponse } from './__mocks__/list-my-flags-response'
import { listExperimentsAPIResponse } from './__mocks__/list-web-experiments-response'
import { listWebVitalsAPIResponse } from './__mocks__/list-web-vitals-response'
import { MenuState, toolbarLogic } from './bar/toolbarLogic'
import { toolbarConfigLogic } from './toolbarConfigLogic'
import { TOOLBAR_ID } from './utils'

function useToolbarStyles(): void {
    useOnMountEffect(() => {
        const head = document.getElementsByTagName('head')[0]
        const shadowRoot = window.document.getElementById(TOOLBAR_ID)?.shadowRoot
        const styleTags: HTMLStyleElement[] = Array.from(head.getElementsByTagName('style'))
        styleTags.forEach((tag) => {
            const style = document.createElement('style')
            const text = tag.innerText
            style.appendChild(document.createTextNode(text))
            shadowRoot?.appendChild(style)
        })
    })
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

type Story = StoryObj<{}>

type ToolbarStoryProps = {
    menu?: MenuState
    minimized?: boolean
    unauthenticated?: boolean
    theme?: 'light' | 'dark'
}

const BasicTemplate = (props: ToolbarStoryProps): JSX.Element => {
    const toolbarParams: ToolbarParams = {
        accessToken: props.unauthenticated ? undefined : 'UExb1dCsoqBtrhrZYxzmxXQ7XdjVH5Ea_zbQjTFuJqk',
        actionId: undefined,
        userIntent: undefined,
        dataAttributes: ['data-attr'],
        apiURL: '/',
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
                },
                isAuthenticated: props.unauthenticated ?? true,
                supportedCompression: ['gzip', 'gzip-js', 'lz64'],
                featureFlags: {
                    'web-experiments': true,
                    'web-vitals': true,
                    'web-vitals-toolbar': true,
                },
                sessionRecording: {
                    endpoint: '/s/',
                },
            },
            '/api/element/stats/': listHeatmapStatsAPIResponse,
            '/api/projects/@current/feature_flags/my_flags': listMyFlagsAPIResponse,
            '/api/projects/@current/actions/': listActionsAPIResponse,
            '/api/projects/@current/web_experiments/': listExperimentsAPIResponse,
            '/api/environments/@current/web_vitals/': listWebVitalsAPIResponse,
            '/api/users/@me/hedgehog_config/': {},
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
    }, [Object.values(props)]) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="min-h-[32rem]">
            <div>The toolbar should show up now! Click it to open.</div>
            <button>Click Me</button>
            <ToolbarApp {...toolbarParams} disableExternalStyles />
        </div>
    )
}

export const Default: Story = {
    render: () => <BasicTemplate />,
}

export const Unauthenticated: Story = {
    render: () => <BasicTemplate unauthenticated />,
}

export const Minimized: Story = {
    render: () => <BasicTemplate minimized />,
}

export const Heatmap: Story = {
    render: () => <BasicTemplate menu="heatmap" />,
}

export const Inspect: Story = {
    render: () => <BasicTemplate menu="inspect" />,
}

export const Actions: Story = {
    render: () => <BasicTemplate menu="actions" />,
}

export const FeatureFlags: Story = {
    render: () => <BasicTemplate menu="flags" />,
}

export const EventsDebuggerEmpty: Story = {
    render: () => <BasicTemplate menu="debugger" />,
}

export const Experiments: Story = {
    render: () => <BasicTemplate menu="experiments" />,
}

export const ExperimentsDisabledInParent: Story = {
    render: () => {
        // fake that the host site posthog config disables web experiments
        window.parent.posthog = { config: { disable_web_experiments: true } }
        return <BasicTemplate menu="experiments" />
    },
}

export const WebVitals: Story = {
    render: () => <BasicTemplate menu="web-vitals" />,
}

// Dark theme
export const DefaultDark: Story = {
    render: () => <BasicTemplate theme="dark" />,
}

export const MinimizedDark: Story = {
    render: () => <BasicTemplate theme="dark" minimized />,
}

export const HeatmapDark: Story = {
    render: () => <BasicTemplate theme="dark" menu="heatmap" />,
}

export const InspectDark: Story = {
    render: () => <BasicTemplate theme="dark" menu="inspect" />,
}

export const ActionsDark: Story = {
    render: () => <BasicTemplate theme="dark" menu="actions" />,
}

export const FeatureFlagsDark: Story = {
    render: () => <BasicTemplate theme="dark" menu="flags" />,
}

export const EventsDebuggerEmptyDark: Story = {
    render: () => <BasicTemplate theme="dark" menu="debugger" />,
}

export const WebVitalsDark: Story = {
    render: () => <BasicTemplate theme="dark" menu="web-vitals" />,
}
