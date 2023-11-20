import '~/styles'
import '~/toolbar/styles.scss'

import { useEffect } from 'react'
import { Meta } from '@storybook/react'

import { ToolbarApp } from '~/toolbar/ToolbarApp'
import { ToolbarParams } from '~/types'
import { useStorybookMocks } from '~/mocks/browser'
import { listMyFlagsAPIResponse } from './__mocks__/list-my-flags-response'
import { useActions, useMountedLogic } from 'kea'
import { MenuState, toolbarButtonLogic } from './bar/toolbarButtonLogic'
import { toolbarLogic } from './toolbarLogic'
import { listActionsAPIResponse } from './__mocks__/list-actions-response'
import { listHetmapStatsAPIResponse } from './__mocks__/list-heatmap-stats-response'

const toolbarParams: ToolbarParams = {
    temporaryToken: 'UExb1dCsoqBtrhrZYxzmxXQ7XdjVH5Ea_zbQjTFuJqk',
    actionId: undefined,
    userIntent: undefined,
    dataAttributes: ['data-attr'],
    apiURL: '/',
    jsURL: 'http://localhost:8234/',
    userEmail: 'foobar@posthog.com',
}

const meta: Meta = {
    title: 'Scenes-Other/Toolbar',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type ToolbarStoryProps = {
    menu?: MenuState
    minimized?: boolean
}

const BasicTemplate = (props: ToolbarStoryProps): JSX.Element => {
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
                isAuthenticated: true,
                supportedCompression: ['gzip', 'gzip-js', 'lz64'],
                featureFlags: {},
                sessionRecording: {
                    endpoint: '/s/',
                },
            },
            '/api/element/stats/': listHetmapStatsAPIResponse,
            '/api/projects/@current/feature_flags/my_flags': listMyFlagsAPIResponse,
            '/api/projects/@current/actions/': listActionsAPIResponse,
        },
    })

    useMountedLogic(toolbarLogic(toolbarParams))

    const { setVisibleMenu, setDragPosition, toggleMinimized } = useActions(toolbarButtonLogic)

    useEffect(() => {
        setDragPosition(50, 50)
        setVisibleMenu(props.menu || 'none')
        toggleMinimized(props.minimized ?? false)
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
