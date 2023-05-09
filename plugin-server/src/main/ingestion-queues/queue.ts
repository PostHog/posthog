import { Hub } from '../../types'
import Piscina from '../../worker/piscina'

export function pauseQueueIfWorkerFull(_: undefined | (() => void | Promise<void>), __: Hub, ___?: Piscina): void {
    return
}
