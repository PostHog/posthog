import { once } from 'events'
import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { Actuation } from '../environment/environment'
import { CardFault, SesThrottleParams } from '../provider-edge'
import type { ApplyContext, ValveDefinition } from './valves'

async function unlessAborted<T>(work: Promise<T>, signal: AbortSignal): Promise<T | undefined> {
    const settled = new AbortController()
    const aborted = once(signal, 'abort', { signal: settled.signal }).then(
        () => undefined,
        () => undefined
    )
    work.catch(() => undefined)
    try {
        return await Promise.race([work, aborted])
    } finally {
        settled.abort()
    }
}

async function edgeFault(
    { edgeUrl, pollMs, faultObservedWithinMs, signal }: ApplyContext,
    fault: CardFault
): Promise<Actuation> {
    const added = await internalFetch(`${edgeUrl}/_faults`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(fault),
    })
    const body = await added.text()
    if (added.status !== 201) {
        throw new Error(`The edge refused the ${fault.name} fault with ${added.status}: ${body}`)
    }
    const { id } = parseJSON(body) as { id: string }
    const applied = async (): Promise<number> => {
        const response = await internalFetch(`${edgeUrl}/_faults/${id}`)
        const text = await response.text()
        if (response.status !== 200) {
            throw new Error(`The edge answered ${response.status} for the ${fault.name} fault: ${text}`)
        }
        return (parseJSON(text) as { applied: number }).applied
    }
    return {
        observed: async () => {
            const deadline = Date.now() + faultObservedWithinMs
            while (!signal.aborted) {
                const count = await unlessAborted(applied(), signal)
                if (count === undefined) {
                    return false
                }
                if (count > 0) {
                    return true
                }
                if (Date.now() >= deadline) {
                    return false
                }
                await sleep(pollMs, undefined, { signal }).catch(() => undefined)
            }
            return false
        },
        release: async () => {
            const removed = await internalFetch(`${edgeUrl}/_faults/${id}`, { method: 'DELETE' })
            await removed.text()
            if (removed.status !== 204 && removed.status !== 404) {
                throw new Error(`The edge did not remove the ${fault.name} fault: it answered ${removed.status}`)
            }
        },
    }
}

export const sesThrottle: ValveDefinition = {
    name: 'ses.throttle',
    params: SesThrottleParams,
    target: z.literal('ses'),
    apply: (context, _target, dose) =>
        edgeFault(context, { name: 'ses.throttle', params: SesThrottleParams.parse(dose) }),
}
