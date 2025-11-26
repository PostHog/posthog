import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { NATIVE_DRAG_DATA_MIME, UNIVERSAL_DND_MIME } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { calculateMovePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

export type DndDescriptor = {
    type: string
    ref: string
    name?: string
    path?: string
    href?: string
    data?: Record<string, any>
}

export type DndDropContext = {
    source: DndDescriptor
    target?: DndDescriptor | null
    nativeEvent?: DragEvent | null
}

export type DndHandler = {
    id: string
    priority?: number
    canHandle?: (context: DndDropContext) => boolean
    onDrop: (context: DndDropContext) => void | boolean | Promise<void | boolean>
}

export type DndRequest = {
    source: DndDescriptor
    target?: DndDescriptor | null
    nativeEvent?: DragEvent | null
    localHandlers?: DndHandler[]
}

export function createProjectTreeDescriptor(entry: FileSystemEntry, name?: string, logicKey?: string): DndDescriptor {
    return {
        type: `project-tree/${entry.type ?? 'item'}`,
        ref: entry.ref || entry.path || entry.id || name || 'project-tree-item',
        name: name || entry.name || entry.path || entry.ref || entry.id || undefined,
        path: entry.path,
        href: typeof entry.href === 'string' ? entry.href : undefined,
        data: {
            item: entry,
            logicKey,
        },
    }
}

export function decodeDndPayload(raw: string | null): DndDescriptor[] {
    if (!raw) {
        return []
    }

    try {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed)) {
            return parsed.flatMap((item) => decodeDndPayload(JSON.stringify(item)))
        }

        if (parsed?.dnd) {
            return [parsed.dnd]
        }

        if (parsed?.type && parsed?.ref) {
            return [parsed as DndDescriptor]
        }
    } catch {}

    return []
}

export function extractDndDescriptorsFromEvent(event: DragEvent): DndDescriptor[] {
    const types = Array.from(event.dataTransfer?.types || [])
    const allDescriptors: DndDescriptor[] = []

    const primaryPayload =
        event.dataTransfer?.getData(UNIVERSAL_DND_MIME) || event.dataTransfer?.getData(NATIVE_DRAG_DATA_MIME)
    allDescriptors.push(...decodeDndPayload(primaryPayload || null))

    const uriList = event.dataTransfer?.getData('text/uri-list')
    const text = event.dataTransfer?.getData('text/plain')

    if (!allDescriptors.length && (uriList || text)) {
        const href = uriList || (text?.startsWith('http') ? text : undefined)
        if (href) {
            allDescriptors.push({
                type: 'url',
                ref: href,
                name: href,
                href,
                data: { uriList: uriList || null, text: text || null },
            })
        } else if (text) {
            allDescriptors.push({
                type: 'text',
                ref: text,
                name: text,
                data: { text },
            })
        }
    }

    // Track what kinds of payloads were available
    if (allDescriptors.length) {
        allDescriptors.forEach((descriptor) => {
            descriptor.data = {
                ...descriptor.data,
                dataTransferTypes: types,
            }
        })
    }

    return allDescriptors
}

export const dndLogic = kea([
    path(['lib', 'dndLogic']),
    connect({
        actions: [projectTreeDataLogic, ['moveItem']],
    }),
    actions({
        registerGlobalHandler: (handler: DndHandler) => ({ handler }),
        unregisterGlobalHandler: (id: string) => ({ id }),
        handleDrop: (request: DndRequest) => ({ request }),
    }),
    reducers({
        globalHandlers: [
            [],
            {
                registerGlobalHandler: (state, { handler }) =>
                    [...state.filter((h: DndHandler) => h.id !== handler.id), handler].sort(
                        (a: DndHandler, b: DndHandler) => (b.priority ?? 0) - (a.priority ?? 0)
                    ),
                unregisterGlobalHandler: (state, { id }) => state.filter((handler: DndHandler) => handler.id !== id),
            },
        ],
    }),
    listeners(({ values }) => ({
        handleDrop: async ({ request }) => {
            const { source, target, nativeEvent, localHandlers = [] } = request

            const sortedLocal = [...localHandlers].sort(
                (a: DndHandler, b: DndHandler) => (b.priority ?? 0) - (a.priority ?? 0)
            )
            const handlers = [...sortedLocal, ...values.globalHandlers]

            for (const handler of handlers) {
                if (!handler) {
                    continue
                }

                if (handler.canHandle && !handler.canHandle({ source, target, nativeEvent })) {
                    continue
                }

                const result = await handler.onDrop({ source, target, nativeEvent })
                if (result === false) {
                    break
                }
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.registerGlobalHandler({
            id: 'project-tree/global-drop',
            priority: 100,
            canHandle: ({ source, target }) =>
                source.type.startsWith('project-tree/') && (target?.type?.startsWith('project-tree/') ?? false),
            onDrop: ({ source, target }) => {
                const item = source.data?.item as FileSystemEntry | undefined
                const logicKey = source.data?.logicKey || 'project-tree'
                const targetPath = target?.path || target?.data?.path || target?.ref || ''

                if (!item || !targetPath) {
                    return
                }

                if (target?.type === 'project-tree/file') {
                    lemonToast.error("You can't drop an item into a file. Drop it into a folder instead.")
                    return false
                }

                const { newPath, isValidMove } = calculateMovePath(item, targetPath)
                if (isValidMove) {
                    actions.moveItem(item, newPath, false, logicKey)
                    return false
                }

                return false
            },
        })
    }),
])
