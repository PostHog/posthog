import { CanvasArg, canvasMutationData, canvasMutationParam, eventWithTime } from '@rrweb/types'
import { captureException } from '@sentry/react'
import { canvasMutation, EventType, IncrementalSource, Replayer } from 'rrweb'
import { ReplayPlugin } from 'rrweb/typings/types'

import { deserializeCanvasArg } from './deserialize-canvas-args'

function isCanvasMutation(e: eventWithTime): boolean {
    return e.type === EventType.IncrementalSnapshot && e.data.source === IncrementalSource.CanvasMutation
}

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
        handler: async (e: eventWithTime, isSync: boolean, { replayer }: { replayer: Replayer }) => {
            // skip when fast forwarding
            if (isSync) {
                const isCanvas = isCanvasMutation(e)

                if (isCanvas) {
                    const data = e.data as canvasMutationData
                    const source = replayer.getMirror().getNode(data.id) as HTMLCanvasElement
                    const target = canvases.get(data.id) || (source && cloneCanvas(data.id, source))

                    if (!target) {
                        return
                    }

                    target.width = source.clientWidth
                    target.height = source.clientHeight

                    await canvasMutation({
                        event: e,
                        mutation: data,
                        target: target,
                        imageMap,
                        canvasEventMap,
                        errorHandler: (error: any) => {
                            if (error instanceof Error) {
                                captureException(error)
                            } else {
                                console.error(error)
                            }
                        },
                    })

                    const img = containers.get(data.id)
                    if (img) {
                        img.src = target.toDataURL()
                    }
                }
            }
        },
    } as ReplayPlugin
}
