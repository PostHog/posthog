import { useActions } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonInput, SpinnerOverlay } from '@posthog/lemon-ui'

import { JSONContent } from 'lib/components/RichContentEditor/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'

type NotebookNodeEmbedAttributes = {
    src?: string
    width?: string | number
    height?: string | number
}

const IFRAME_MATCHER = /(?:<iframe[^>]*)(?:(?:\/>)|(?:>.*?<\/iframe>))/gi

const parseIframeString = (input: string): NotebookNodeEmbedAttributes | null => {
    const parser = new DOMParser()
    const doc = parser.parseFromString(input, 'text/html')
    const firstIframe = doc.getElementsByTagName('iframe')

    if (firstIframe[0]) {
        return {
            src: firstIframe[0].src,
            height: firstIframe[0].height,
        }
    }

    return null
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeEmbedAttributes>): JSX.Element => {
    const { src } = attributes
    const { setTitlePlaceholder, toggleEditing } = useActions(notebookNodeLogic)
    const [loaded, setLoaded] = useState(false)

    const validUrl = useMemo(() => {
        // Check the src exists and is a valid URL beginning with http
        if (!src || /^https?:\/\//.test(src) === false) {
            return null
        }
        try {
            return new URL(src)
        } catch {
            return null
        }
    }, [src])

    useEffect(() => {
        if (validUrl) {
            setTitlePlaceholder(validUrl?.hostname)
        } else {
            setTitlePlaceholder('Embedded iframe')
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [validUrl])

    return (
        <>
            {validUrl ? (
                <>
                    <iframe
                        className="w-full h-full"
                        src={validUrl.toString()}
                        allowFullScreen
                        onLoad={() => {
                            setLoaded(true)
                        }}
                    />
                    {!loaded ? <SpinnerOverlay /> : null}
                </>
            ) : (
                <div className="flex-1 flex flex-col justify-center items-center">
                    {src ? <p>The given URL is not valid.</p> : <p>No URL configured</p>}
                    <LemonButton type="primary" onClick={() => toggleEditing(true)}>
                        Configure
                    </LemonButton>
                </div>
            )}
        </>
    )
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeEmbedAttributes>): JSX.Element => {
    const [localUrl, setLocalUrl] = useState(attributes.src)
    const { toggleEditing } = useActions(notebookNodeLogic)

    const save = (): void => {
        if (!localUrl) {
            return
        }
        const params = parseIframeString(localUrl) ?? {
            src: localUrl,
        }
        setLocalUrl(params.src)
        updateAttributes(params)
        toggleEditing(false)
    }

    useEffect(() => setLocalUrl(attributes.src), [attributes.src])

    const hasChanges = localUrl !== attributes.src

    return (
        <div className="p-3 flex items-center flex-wrap gap-2">
            <LemonInput
                value={localUrl}
                onChange={setLocalUrl}
                onPressEnter={save}
                placeholder="Enter URL or <iframe> code"
                className="flex-1"
                autoFocus
            />
            <LemonButton type="primary" onClick={save} disabledReason={!hasChanges ? 'Not changed' : null}>
                Save
            </LemonButton>
        </div>
    )
}

export const NotebookNodeEmbed = createPostHogWidgetNode<NotebookNodeEmbedAttributes>({
    nodeType: NotebookNodeType.Embed,
    titlePlaceholder: 'Embed',
    Component,
    Settings,
    settingsIcon: 'gear',
    serializedText: (attrs) => `(embedded iframe:${attrs.src})`,
    heightEstimate: 400,
    minHeight: 100,
    resizeable: true,
    expandable: false,
    autoHideMetadata: false,
    attributes: {
        src: {},
        width: {},
        height: {},
    },
    pasteOptions: {
        find: IFRAME_MATCHER,
        getAttributes: async (match) => {
            return parseIframeString(match[0]) ?? {}
        },
    },
})

export function buildNodeEmbed(): JSONContent {
    return {
        type: NotebookNodeType.Embed,
        attrs: {
            __init: {
                showSettings: true,
            },
        },
    }
}
