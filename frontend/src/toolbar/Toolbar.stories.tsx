import 'react-toastify/dist/ReactToastify.css'
import '~/styles'
import '~/toolbar/styles.scss'

import React, { useEffect } from 'react'
import { Meta } from '@storybook/react'

import { ToolbarApp } from '~/toolbar/ToolbarApp'
import { EditorProps } from '~/types'
import { useStorybookMocks } from '~/mocks/browser'

const editorParams: EditorProps = {
    temporaryToken: 'UExb1dCsoqBtrhrZYxzmxXQ7XdjVH5Ea_zbQjTFuJqk',
    actionId: undefined,
    userIntent: undefined,
    dataAttributes: ['data-attr'],
    apiURL: '/',
    jsURL: 'http://localhost:8234/',
    userEmail: 'foobar@posthog.com',
}

export default {
    title: 'Scenes-Other/Toolbar',
    parameters: { layout: 'fullscreen', options: { showPanel: false }, viewMode: 'story' },
} as Meta

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

export const Authenticated = (): JSX.Element => {
    useToolbarStyles()

    useStorybookMocks({
        get: {
            '/decide': {
                config: {
                    enable_collect_everything: true,
                },
                editorParams: {
                    toolbarVersion: 'toolbar',
                    jsURL: editorParams.jsURL,
                },
                isAuthenticated: true,
                supportedCompression: ['gzip', 'gzip-js', 'lz64'],
                featureFlags: {},
                sessionRecording: {
                    endpoint: '/s/',
                },
            },
            '/api/element/stats': () => [200, []],
            '/api/projects/@current/feature_flags/my_flags': () => [200, []],
            '/api/organizations/@current/members/?limit=200': { results: [] },
        },
    })

    return (
        <div>
            <div>The toolbar should show up now! Click it to open.</div>
            <button>Click Me</button>
            <ToolbarApp {...editorParams} disableExternalStyles />
        </div>
    )
}

export const UnAuthenticated = (): JSX.Element => {
    useToolbarStyles()

    return (
        <div>
            <div>The toolbar should show up now!</div>
            <button>Click Me</button>
            <ToolbarApp {...editorParams} disableExternalStyles />
        </div>
    )
}
