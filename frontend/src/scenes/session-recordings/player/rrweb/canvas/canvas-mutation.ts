import { CanvasContext, canvasMutationCommand, canvasMutationData, canvasMutationParam } from '@rrweb/types'
import { Replayer } from 'rrweb'

import canvas2DMutation from './2d'

export default async function canvasMutation({
    event,
    mutation,
    target,
    imageMap,
    canvasEventMap,
    errorHandler,
}: {
    event: Parameters<Replayer['applyIncremental']>[0]
    mutation: canvasMutationData
    target: HTMLCanvasElement
    imageMap: Replayer['imageMap']
    canvasEventMap: Replayer['canvasEventMap']
    errorHandler: Replayer['warnCanvasMutationFailed']
}): Promise<void> {
    try {
        const precomputedMutation: canvasMutationParam = canvasEventMap.get(event) || mutation

        const commands: canvasMutationCommand[] =
            'commands' in precomputedMutation ? precomputedMutation.commands : [precomputedMutation]

        if ([CanvasContext.WebGL, CanvasContext.WebGL2].includes(mutation.type)) {
            return
        }
        // default is '2d' for backwards compatibility (rrweb below 1.1.x)
        await canvas2DMutation({
            event,
            mutations: commands,
            target,
            imageMap,
            errorHandler,
        })
    } catch (error) {
        errorHandler(mutation, error)
    }
}
