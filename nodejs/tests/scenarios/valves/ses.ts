import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { Actuation } from '../environment/environment'
import type { CardFault } from '../provider-edge'
import type { ApplyContext, ValveDefinition } from './valves'

async function edgeFault(
    { edgeUrl, pollMs, faultObservedWithinMs }: ApplyContext,
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
        return response.status === 200 ? (parseJSON(text) as { applied: number }).applied : 0
    }
    return {
        observed: async () => {
            const deadline = Date.now() + faultObservedWithinMs
            while ((await applied()) === 0) {
                if (Date.now() >= deadline) {
                    return false
                }
                await sleep(pollMs)
            }
            return true
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

const SesThrottleDose = z.object({ rate: z.number().int().min(1) }).strict()

export const sesThrottle: ValveDefinition = {
    name: 'ses.throttle',
    params: SesThrottleDose,
    target: z.literal('ses'),
    apply: (context, _target, dose) =>
        edgeFault(context, { name: 'ses.throttle', params: SesThrottleDose.parse(dose), dose: { share: 1 } }),
}
