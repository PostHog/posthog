import { CanvasArg, type canvasMutationData, type canvasMutationParam, eventWithTime } from '@rrweb/types'
import { EventType, IncrementalSource, Replayer } from 'rrweb'
import { ReplayPlugin } from 'rrweb/typings/types'

import canvasMutation from './canvas-mutation'
import { deserializeCanvasArg } from './deserialize-canvas-args'

export function CanvasReplayerPlugin(events: eventWithTime[]): ReplayPlugin {
    const canvases = new Map<number, HTMLCanvasElement>([])
    const containers = new Map<number, HTMLImageElement>([])
    const imageMap = new Map<eventWithTime | string, HTMLImageElement>()
    const canvasEventMap = new Map<eventWithTime | string, canvasMutationParam>()

    /**
     * Taken from rrweb: https://github.com/rrweb-io/rrweb/blob/8e318c44f26ac25c80d8bd0811f19f5e3fe9903b/packages/rrweb/src/replay/index.ts#L1039
     */
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

    /**
     * Clone canvas node, change parent document of node to current document, and
     * insert an image element to original node (i.e. canvas inside of iframe).
     *
     * The image element is saved to `containers` map, which will later get
     * written to when replay is being played.
     */
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
        /**
         * When document is first built, we want to preload canvas events. After a
         * `canvas` element is built (in rrweb), insert an image element which will
         * be used to mirror the drawn canvas.
         */
        onBuild: (node, { id }) => {
            if (!node) {
                return
            }

            if (node.nodeName === 'CANVAS' && node.nodeType === 1) {
                // Add new image container that will be written to
                const el = containers.get(id) || document.createElement('img')
                ;(node as HTMLCanvasElement).appendChild(el)
                containers.set(id, el)
            }
        },

        /**
         * Mutate canvas outside of iframe, then export the canvas as an image, and
         * draw inside of the image el inside of replay canvas.
         */
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
