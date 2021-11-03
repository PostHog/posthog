import 'react-toastify/dist/ReactToastify.css'
import '~/styles'
import '~/toolbar/styles.scss'

import React, { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { keaStory } from 'lib/storybook/kea-story'

import { ToolbarApp } from '~/toolbar/ToolbarApp'
import toolbarJson from './__stories__/toolbar.json'

import { EditorProps } from '~/types'

export default {
    title: 'Toolbar/Authenticated',
} as Meta

const toolbarStory = (json: Record<string, any>): (() => JSX.Element) => {
    const { rawApiURL, rawJsUrl, ...rest } = json?.toolbar?.toolbarLogic || {}
    const editorParams: EditorProps = { ...rest, apiURL: rawApiURL, jsURL: rawJsUrl, userEmail: 'foobar@posthog.com' }
    return keaStory(() => {
        useEffect(() => {
            const head = document.getElementsByTagName('head')[0]
            const shadowRoot = window.document.getElementById('__POSTHOG_TOOLBAR__')?.shadowRoot
            const styleTags: HTMLStyleElement[] = Array.from(head.getElementsByTagName('style'))
            styleTags.forEach((tag) => {
                const style = document.createElement('style')
                style.appendChild(document.createTextNode(tag.innerText))
                shadowRoot?.appendChild(tag)
            })
        }, [])
        return (
            <div>
                <div>The toolbar should show up now!</div>
                <button>Click Me</button>
                <ToolbarApp {...editorParams} disableExternalStyles />
            </div>
        )
    }, json)
}

export const Open = toolbarStory(toolbarJson)
