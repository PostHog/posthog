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

    it('preserves an absolute delivery deadline on queued fetches', async () => {
        const expiresAt = Date.now() + 1000
        expect((await callFetch({ expires_at: expiresAt })).expires_at).toBe(expiresAt)
        expect((await callFetch({})).expires_at).toBeUndefined()
    })

    // Receivers dedupe on webhook-id, so two deliveries must never share one. A
    // single invocation can call fetch repeatedly, which anything derived from the
    // invocation would collapse into one id.
    it('gives every signed fetch call its own webhook id', async () => {
        const first = await callFetch({ standard_webhooks: { secret_input: 'signing_secret' } })
        const second = await callFetch({ standard_webhooks: { secret_input: 'signing_secret' } })

        expect(first.standard_webhooks?.secret_input).toBe('signing_secret')
        expect(first.standard_webhooks?.webhook_id).toBeTruthy()
        expect(second.standard_webhooks?.webhook_id).not.toBe(first.standard_webhooks?.webhook_id)
    })
})
