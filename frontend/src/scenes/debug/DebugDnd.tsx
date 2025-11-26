import { DndContext, useDroppable } from '@dnd-kit/core'
import clsx from 'clsx'
import { useActions } from 'kea'
import { useState } from 'react'

import { DndDescriptor, dndLogic, extractDndDescriptorsFromEvent } from 'lib/dndLogic'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

type DroppedItem = {
    id: string
    source: string
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
    const { handleDrop: dispatchDrop } = useActions(dndLogic)

    const descriptorToDroppedItem = (descriptor: DndDescriptor): DroppedItem => ({
        id: descriptor.ref || crypto.randomUUID(),
        source: descriptor.type || 'unknown',
        label: descriptor.name || descriptor.path || descriptor.href || descriptor.ref || 'Unknown drop',
        href: descriptor.href,
        path: descriptor.path,
        ref: descriptor.ref,
        metadata: descriptor.data || {},
        dataTransferTypes: descriptor.data?.dataTransferTypes || [],
    })

    const handleDropEvent = (event: React.DragEvent<HTMLDivElement>): void => {
        event.preventDefault()
        event.stopPropagation()
        setIsDragging(false)

        const target: DndDescriptor = { type: 'debug/dropzone', ref: 'debug-dnd', name: 'Debug dropzone' }
        const nativeEvent = event.nativeEvent as DragEvent
        const descriptors = nativeEvent ? extractDndDescriptorsFromEvent(nativeEvent) : []

        const payloads = descriptors.length
            ? descriptors
            : [
                  {
                      type: 'unknown',
                      ref: crypto.randomUUID(),
                      name: 'Unknown drop',
                      data: {},
                  },
              ]

        payloads.forEach((descriptor) => {
            dispatchDrop({
                source: descriptor,
                target,
                nativeEvent,
                localHandlers: [
                    {
                        id: `debug-dnd-record-${descriptor.ref}`,
                        priority: 1000,
                        onDrop: () => {
                            setItems((current) => [descriptorToDroppedItem(descriptor), ...current])
                            return false
                        },
                    },
                ],
            })
        })
    }

    return (
        <SceneContent>
            <SceneTitleSection name="Drag and drop debug" resourceType={{ type: 'insight/hog' }} />

            <DndContext>
                <div className="space-y-4">
                    <div
                        ref={setNodeRef}
                        onDrop={handleDropEvent}
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
                        Drop URLs, project tree items, or anything else here
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
                                    item.source.startsWith('project-tree') ? 'Project tree' : item.source,
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
