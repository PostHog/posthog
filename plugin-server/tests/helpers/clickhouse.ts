import { performance } from 'perf_hooks'

import { status } from '../../src/utils/status'
import { delay } from '../../src/utils/utils'

export async function delayUntilEventIngested<T extends any[] | number>(
    fetchData: () => T | Promise<T>,
    minLength = 1,
    delayMs = 100,
    maxDelayCount = 100
): Promise<T> {
    const timer = performance.now()
    let data: T
    let dataLength = 0
    for (let i = 0; i < maxDelayCount; i++) {
        data = await fetchData()
        dataLength = typeof data === 'number' ? data : data.length
        status.debug(
            `Waiting. ${Math.round((performance.now() - timer) / 100) / 10}s since the start. ${dataLength} event${
                dataLength !== 1 ? 's' : ''
            }.`
        )
        if (dataLength >= minLength) {
            return data
        }
        await delay(delayMs)
    }
    throw Error(`Failed to get data in time, got ${JSON.stringify(data)}`)
}
