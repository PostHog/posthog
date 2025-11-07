import { useState } from 'react'

import { useKeyHeld } from 'lib/hooks/useKeyHeld'

import { useNotebookNode } from '~/scenes/notebooks/Nodes/NotebookNodeContext'
import { getIconTypeFromUrl } from '~/scenes/urls'

import { draggableLinkLogic } from './draggableLinkLogic'

export type DraggableLinkBaseProps = {
    href?: string
    properties?: Record<string, any>
    onlyWithModifierKey?: boolean
}

export function useDraggableLink({ href, properties, onlyWithModifierKey }: DraggableLinkBaseProps): {
    isDragging: boolean
    draggable: boolean
    elementProps: Pick<React.HTMLAttributes<HTMLElement>, 'onDragStart' | 'onDragEnd'>
} {
    // TRICKY: We do this instead of hooks as there is some weird cyclic issue in tests
    const mountedDraggableLinkLogic = draggableLinkLogic.findMounted()

    const [isDragging, setIsDragging] = useState(false)

    const isInNotebook = useNotebookNode()
    const hasDragOptions = !!href

    const altKeyHeld = useKeyHeld('Alt')
    const dragModeActive = onlyWithModifierKey ? altKeyHeld : true

    if (!hasDragOptions || isInNotebook || !dragModeActive) {
        return {
            isDragging: false,
            draggable: false,
            elementProps: {},
        }
    }

    return {
        isDragging,
        draggable: true,
        elementProps: {
            onDragStart: (e: any) => {
                setIsDragging(true)
                mountedDraggableLinkLogic?.actions.startDropMode()
                if (href) {
                    const title: string = e.currentTarget?.title || e.currentTarget?.textContent || ''
                    const url = window.location.origin + href
                    const iconType = getIconTypeFromUrl(href)
                    e.dataTransfer.setData('text/uri-list', url)
                    e.dataTransfer.setData('text/plain', url)
                    // Add data for shortcuts and other potential targets
                    e.dataTransfer.setData('text/href', href)
                    e.dataTransfer.setData('text/title', title)
                    // Detect icon type from URL during drag
                    e.dataTransfer.setData('text/iconType', iconType)

                    // Extract node from properties if present for NotebookPanelDropzone (backward compatibility)
                    if (properties?.node) {
                        e.dataTransfer.setData('node', properties.node)
                    }
                }
                properties && e.dataTransfer.setData('properties', JSON.stringify(properties))
            },
            onDragEnd: () => {
                setIsDragging(false)
                mountedDraggableLinkLogic?.actions.endDropMode()
            },
        },
    }
}
