import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { NotebookNodeAttributeProperties, NotebookNodeProps } from '../Notebook/utils'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useEffect, useMemo, useState } from 'react'
import { useActions } from 'kea'
import { notebookNodeLogic } from './notebookNodeLogic'

const iframeRegex = /(?:<iframe[^>]*)(?:(?:\/>)|(?:>.*?<\/iframe>))/

const getIframeSrc = (src: string): string | null => {
    const matches = src.match(iframeRegex)
    if (matches) {
        const iframe = matches[0]
        const srcMatch = iframe.match(/src="([^"]*)"/)
        if (srcMatch) {
            return srcMatch[1]
        }
    }
    return null
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeEmbedAttributes>): JSX.Element => {
    const src = attributes.src
    const { setTitlePlaceholder, toggleEditing } = useActions(notebookNodeLogic)

    const validUrl = useMemo(() => {
        if (!src) {
            return null
        }
        try {
            return new URL(src)
        } catch (e) {
            return null
        }
    }, [src])

    useEffect(() => {
        if (validUrl) {
            setTitlePlaceholder(validUrl?.hostname)
        } else {
            setTitlePlaceholder('Embedded iframe')
        }
    }, [validUrl])

    return (
        <>
            {validUrl ? (
                <iframe className="w-full h-full" src={validUrl.toString()} />
            ) : (
                <div className="flex-1 flex flex-col justify-center items-center">
                    {src ? <p>The given URL is not valid.</p> : <p>No URL configured</p>}
                    <LemonButton type="primary" onClick={() => toggleEditing()}>
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

    const save = (): void => {
        if (!localUrl) {
            return
        }
        const newValue = getIframeSrc(localUrl) ?? localUrl
        setLocalUrl(newValue)
        updateAttributes({ src: newValue })
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
            />
            <LemonButton type="primary" onClick={save} disabledReason={!hasChanges ? 'Not changed' : null}>
                Save
            </LemonButton>
        </div>
    )
}

type NotebookNodeEmbedAttributes = {
    src?: string
}

export const NotebookNodeEmbed = createPostHogWidgetNode<NotebookNodeEmbedAttributes>({
    nodeType: NotebookNodeType.Embed,
    titlePlaceholder: 'Embed',
    Component,
    Settings,
    serializedText: () => {
        // TODO file is null when this runs... should it be?
        return '(embedded iframe)'
    },
    heightEstimate: 400,
    minHeight: 100,
    resizeable: true,
    expandable: false,
    autoHideMetadata: false,
    attributes: {
        file: {},
        src: {},
    },
    // rawPasteOptions: [{
    //     editor: this.editor,
    //     type: NotebookNodeType.Embed,

    //     posthogNodePasteRule({
    //                       editor: this.editor,
    //                       type: this.type,
    //                       ...pasteOptions,
    //                   }),
    // }],
})
