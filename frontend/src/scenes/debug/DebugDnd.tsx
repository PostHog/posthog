import { DndContext, useDroppable } from '@dnd-kit/core'
import clsx from 'clsx'
import { useState } from 'react'

import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { NATIVE_DRAG_DATA_MIME } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

type DroppedItem = {
    id: string
    source: 'url' | 'project-tree' | 'unknown'
    label: string
    href?: string
    path?: string
    ref?: string
    metadata: Record<string, any>
    dataTransferTypes: string[]
}

export function DebugDnd(): JSX.Element {
    const [items, setItems] = useState<DroppedItem[]>([])
    const [isDragging, setIsDragging] = useState(false)
    const { isOver, setNodeRef } = useDroppable({ id: 'debug-dnd-dropzone' })

    const handleDrop = (event: React.DragEvent<HTMLDivElement>): void => {
        event.preventDefault()
        event.stopPropagation()
        setIsDragging(false)

        const dropped: DroppedItem[] = []
        const types = Array.from(event.dataTransfer?.types || [])
        const treeData = event.dataTransfer.getData(NATIVE_DRAG_DATA_MIME)
        const uriList = event.dataTransfer.getData('text/uri-list')
        const text = event.dataTransfer.getData('text/plain')

        if (treeData) {
            try {
                const payload = JSON.parse(treeData)
                dropped.push({
                    id: payload.id || crypto.randomUUID(),
                    source: 'project-tree',
                    label: payload.name || payload.path || payload.id || 'Project tree item',
                    href: payload.href,
                    path: payload.path,
                    ref: payload.ref,
                    metadata: payload,
                    dataTransferTypes: types,
                })
            } catch (error) {
                dropped.push({
                    id: crypto.randomUUID(),
                    source: 'project-tree',
                    label: 'Project tree item',
                    metadata: { error: String(error), raw: treeData },
                    dataTransferTypes: types,
                })
            }
        }

        const url = uriList || (text?.startsWith('http') ? text : undefined)
        if (url) {
            dropped.push({
                id: crypto.randomUUID(),
                source: 'url',
                label: url,
                href: url,
                metadata: { uriList: uriList || null, text: text || null },
                dataTransferTypes: types,
            })
        }

        if (!dropped.length) {
            dropped.push({
                id: crypto.randomUUID(),
                source: 'unknown',
                label: text || 'Unknown drop',
                metadata: { text, uriList },
                dataTransferTypes: types,
            })
        }

        setItems((current) => [...dropped, ...current])
    }

    return (
        <SceneContent>
            <SceneTitleSection name="Drag and drop debug" resourceType={{ type: 'insight/hog' }} />

            <DndContext>
                <div className="space-y-4">
                    <div
                        ref={setNodeRef}
                        onDrop={handleDrop}
                        onDragOver={(event) => {
                            event.preventDefault()
                            setIsDragging(true)
                        }}
                        onDragLeave={() => setIsDragging(false)}
                        className={clsx(
                            'h-64 rounded border border-dashed bg-bg-3000 flex items-center justify-center text-muted font-medium text-lg',
                            (isOver || isDragging) && 'border-primary bg-primary-highlight text-primary'
                        )}
                    >
                        Drop a URL or project tree item here
                    </div>

                    <div className="flex items-center gap-2">
                        <span className="font-semibold">Recent drops</span>
                        <span className="text-muted-alt">(newest first)</span>
                    </div>
                    <LemonDivider />
                    <LemonTable
                        dataSource={items}
                        columns={[
                            {
                                title: 'Source',
                                dataIndex: 'source',
                                render: (_, item) =>
                                    item.source === 'project-tree' ? 'Project tree' : item.source.toUpperCase(),
                            },
                            {
                                title: 'Label',
                                dataIndex: 'label',
                            },
                            {
                                title: 'Href',
                                dataIndex: 'href',
                                render: (_, item) => item.href || '—',
                            },
                            {
                                title: 'Path / ref',
                                key: 'path',
                                render: (_, item) => item.path || item.ref || '—',
                            },
                            {
                                title: 'Metadata',
                                key: 'metadata',
                                render: (_, item) => (
                                    <code className="text-xs whitespace-pre-wrap break-words">
                                        {JSON.stringify(
                                            { ...item.metadata, dataTransferTypes: item.dataTransferTypes },
                                            null,
                                            2
                                        )}
                                    </code>
                                ),
                            },
                        ]}
                        emptyState="Drag something into the drop zone to see its metadata"
                    />
                </div>
            </DndContext>
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: DebugDnd,
}
