import type { canvasMutationCommand } from '@rrweb/types'
import { Replayer } from 'rrweb'

import { deserializeArg } from './deserialize-args'

export default async function canvasMutation({
    event,
    mutations,
    target,
    imageMap,
    errorHandler,
}: {
    event: Parameters<Replayer['applyIncremental']>[0]
    mutations: canvasMutationCommand[]
    target: HTMLCanvasElement
    imageMap: Replayer['imageMap']
    errorHandler: Replayer['warnCanvasMutationFailed']
}): Promise<void> {
    const ctx = target.getContext('2d')

    if (!ctx) {
        errorHandler(mutations[0], new Error('Canvas context is null'))
        return
    }

    // step 1, deserialize args, they may be async
    const mutationArgsPromises = mutations.map(async (mutation: canvasMutationCommand): Promise<unknown[]> => {
        return Promise.all(mutation.args.map(deserializeArg(imageMap, ctx)))
    })
    const args = await Promise.all(mutationArgsPromises)
    // step 2 apply all mutations
    args.forEach((args, index) => {
        const mutation = mutations[index]
        try {
            if (mutation.setter) {
                // skip some read-only type checks
                ;(ctx as unknown as Record<string, unknown>)[mutation.property] = mutation.args[0]
                return
            }
            const original = ctx[mutation.property as Exclude<keyof typeof ctx, 'canvas'>] as (
                ctx: CanvasRenderingContext2D,
                args: unknown[]
            ) => void

            /**
             * We have serialized the image source into base64 string during recording,
             * which has been preloaded before replay.
             * So we can get call drawImage SYNCHRONOUSLY which avoid some fragile cast.
             */
            if (mutation.property === 'drawImage' && typeof mutation.args[0] === 'string') {
                imageMap.get(event)
                original.apply(ctx, mutation.args)
            } else {
                original.apply(ctx, args)
            }
        } catch (error) {
            errorHandler(mutation, error)
        }

        return
    })
}
