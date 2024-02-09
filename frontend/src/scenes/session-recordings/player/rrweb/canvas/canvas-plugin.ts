import { CanvasArg, canvasMutationData, canvasMutationParam, eventWithTime } from '@rrweb/types'
import { EventType, IncrementalSource, Replayer } from 'rrweb'
import { canvasMutation } from 'rrweb/es/rrweb/packages/rrweb/src/replay/canvas'
import { ReplayPlugin } from 'rrweb/typings/types'

import { deserializeCanvasArg } from './deserialize-canvas-args'

export const CanvasReplayerPlugin = (events: eventWithTime[]): ReplayPlugin => {
    const canvases = new Map<number, HTMLCanvasElement>([])
    const containers = new Map<number, HTMLImageElement>([])
    const imageMap = new Map<eventWithTime | string, HTMLImageElement>()
    const canvasEventMap = new Map<eventWithTime | string, canvasMutationParam>()

    const deserializeAndPreloadCanvasEvents = async (data: canvasMutationData, event: eventWithTime): Promise<void> => {
        if (!canvasEventMap.has(event)) {
            const status = { isUnchanged: true }

            if ('commands' in data) {
                const commands = await Promise.all(
                    data.commands.map(async (c) => {
                        const args = await Promise.all(
                            (c.args as CanvasArg[]).map(deserializeCanvasArg(imageMap, null, status))
                        )
                        return { ...c, args }
                    })
                )
                if (status.isUnchanged === false) {
                    canvasEventMap.set(event, { ...data, commands })
                }
            } else {
                const args = await Promise.all(
                    (data.args as CanvasArg[]).map(deserializeCanvasArg(imageMap, null, status))
                )
                if (status.isUnchanged === false) {
                    canvasEventMap.set(event, { ...data, args })
                }
            }
        }
    }

    const cloneCanvas = (id: number, node: HTMLCanvasElement): HTMLCanvasElement => {
        const cloneNode = node.cloneNode() as HTMLCanvasElement
        canvases.set(id, cloneNode)
        document.adoptNode(cloneNode)
        return cloneNode
    }

    const promises: Promise<any>[] = []
    for (const event of events) {
        if (event.type === EventType.IncrementalSnapshot && event.data.source === IncrementalSource.CanvasMutation) {
            promises.push(deserializeAndPreloadCanvasEvents(event.data, event))
        }
    }

    return {
        onBuild: (node, { id }) => {
            if (!node) {
                return
            }

            if (node.nodeName === 'CANVAS' && node.nodeType === 1) {
                const el = containers.get(id) || document.createElement('img')
                ;(node as HTMLCanvasElement).appendChild(el)
                containers.set(id, el)
            }
        },

        // eslint-disable-next-line @typescript-eslint/no-misused-promises
        handler: async (e: eventWithTime, _isSync: boolean, { replayer }: { replayer: Replayer }) => {
            if (e.type === EventType.IncrementalSnapshot && e.data.source === IncrementalSource.CanvasMutation) {
                const source = replayer.getMirror().getNode(e.data.id)
                const target =
                    canvases.get(e.data.id) || (source && cloneCanvas(e.data.id, source as HTMLCanvasElement))

                if (!target) {
                    return
                }

                await canvasMutation({
                    event: e,
                    mutation: e.data,
                    target: target,
                    imageMap,
                    canvasEventMap,
                })

                const img = containers.get(e.data.id)
                if (img) {
                    img.src = target.toDataURL()
                }
            }
        },
    } as ReplayPlugin
}
