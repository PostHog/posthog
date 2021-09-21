import { ExpectFunction } from '~/test/kea-test-utils'
import { BuiltLogic, getPluginContext, isBreakpoint } from 'kea'
import { delay } from 'lib/utils'

export const LISTENER_FINISH_WAIT_TIMEOUT = 3000

export const toFinishAllListeners: ExpectFunction<number> = {
    sync(logic, ms) {
        return [{ operation: 'toFinishAllListeners', logic: logic, payload: ms }]
    },
    async async(_, ms) {
        while (true) {
            const { pendingPromises } = getPluginContext('listeners') as {
                pendingPromises: Map<Promise<void>, [BuiltLogic, string]>
            }
            const promises = Array.from(pendingPromises.keys())
            if (promises.length === 0) {
                break
            }
            await Promise.race([
                delay(ms || LISTENER_FINISH_WAIT_TIMEOUT).then(() => {
                    const count = pendingPromises.size
                    const logicNames = Array.from(pendingPromises.values())
                        .map(([l, k]) => `- ${l.pathString} -> ${k}`)
                        .join('\n')
                    console.error(`Still running ${count} listener${count === 1 ? '' : 's'}:\n${logicNames}`)
                    throw new Error(`Timed out waiting for all listeners.`)
                }),
                Promise.all(promises),
            ]).catch((e) => {
                if (!isBreakpoint(e)) {
                    throw e
                }
            })
        }
    },
}
