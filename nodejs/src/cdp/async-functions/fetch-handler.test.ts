import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'

import { getAsyncFunctionHandler } from '../async-function-registry'
import { CyclotronJobInvocationResult } from '../types'
import './fetch-handler'

describe('fetch handler', () => {
    const callFetch = async (
        fetchOptions: Record<string, any>
    ): Promise<CyclotronInvocationQueueParametersFetchType> => {
        const result = { invocation: {} } as CyclotronJobInvocationResult<any>
        await getAsyncFunctionHandler('fetch')!.execute(['https://example.com', fetchOptions], {} as any, result)
        return result.invocation.queueParameters as CyclotronInvocationQueueParametersFetchType
    }

    // Receivers dedupe on webhook-id, so two deliveries must never share one. A
    // single invocation can call fetch repeatedly, which anything derived from the
    // invocation would collapse into one id.
    it.each(['standard_webhooks', 'hmac_sha256'] as const)(
        'gives every %s signed fetch call its own webhook id',
        async (signing) => {
            const first = await callFetch({ [signing]: { secret_input: 'signing_secret' } })
            const second = await callFetch({ [signing]: { secret_input: 'signing_secret' } })

            expect(first[signing]?.secret_input).toBe('signing_secret')
            expect(first[signing]?.webhook_id).toBeTruthy()
            expect(second[signing]?.webhook_id).not.toBe(first[signing]?.webhook_id)
        }
    )

    it('gives both signers of one fetch call the same webhook id', async () => {
        const queued = await callFetch({
            standard_webhooks: { secret_input: 'signing_secret' },
            hmac_sha256: { secret_input: 'signing_secret' },
        })

        expect(queued.standard_webhooks?.webhook_id).toBeTruthy()
        expect(queued.hmac_sha256?.webhook_id).toBe(queued.standard_webhooks?.webhook_id)
    })
})
