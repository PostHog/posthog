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
            const styleTags: HTMLStyleElement[] = Array.from(document.getElementsByTagName('style'))
            ;(window as any)['__PHGTLB_STYLES__'] = styleTags.map((tag) => {
                const style = document.createElement('style')
                style.appendChild(document.createTextNode(tag.innerText))
                return style
            })
        }, [])
        return (
            <div>
                <div>The toolbar should show up now!</div>
                <button>Click Me</button>
                <ToolbarApp {...editorParams} />
            </div>
        )
    }, json)
}

export const Open = toolbarStory(toolbarJson)
