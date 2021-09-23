import { ExpectFunction } from '~/test/kea-test-utils'
import { BuiltLogic, getPluginContext, isBreakpoint } from 'kea'
import { delay } from 'lib/utils'
import { LISTENER_FINISH_WAIT_TIMEOUT } from '~/test/kea-test-utils/functions/toFinishAllListeners'

export const toFinishListeners: ExpectFunction<number> = {
    sync(logic, ms) {
        return [{ operation: 'toFinishListeners', logic: logic, payload: ms }]
    },
    async async(logic, ms) {
        while (true) {
            const { pendingPromises } = getPluginContext('listeners') as {
                pendingPromises: Map<Promise<void>, [BuiltLogic, string]>
            }
            const promises = Array.from(pendingPromises.entries())
                .filter(([, [l]]) => l === logic)
                .map(([p]) => p)
            if (promises.length === 0) {
                break
            }
            await Promise.race([
                delay(ms || LISTENER_FINISH_WAIT_TIMEOUT).then(() => {
                    const logicNames = Array.from(pendingPromises.values())
                        .filter(([l]) => l === logic)
                        .map(([l, k]) => `- ${l.pathString} -> ${k}`)
                    const count = logicNames.length
                    console.error(`Still running ${count} listener${count === 1 ? '' : 's'}:\n${logicNames.join('\n')}`)
                    throw new Error(`Timed out waiting for listeners in "${logic.pathString}".`)
                }),
                Promise.all(promises).catch((e) => {
                    if (!isBreakpoint(e)) {
                        throw e
                    }
                }),
            ])
        }
    },
}
