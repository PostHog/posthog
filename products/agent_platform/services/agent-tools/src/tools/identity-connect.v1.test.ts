import { describe, expect, it, vi } from 'vitest'

import type { ToolContext } from '@posthog/agent-shared'

import { identityConnectV1 } from './identity-connect.v1'

function ctx(identity?: Partial<NonNullable<ToolContext['identity']>>): ToolContext {
    return { identity, http: {} as never, posthogApiBaseUrl: 'http://x' } as unknown as ToolContext
}

describe('@posthog/identity-connect', () => {
    it('mints a (re)connect link via relink and returns it for the agent to relay', async () => {
        const relink = vi.fn(async () => 'https://app.posthog.test/oauth/authorize/?x=1')
        const res = await identityConnectV1.run({ provider: 'posthog' }, ctx({ relink, resolve: vi.fn() }))
        expect(res).toEqual({ authorize_url: 'https://app.posthog.test/oauth/authorize/?x=1' })
        expect(relink).toHaveBeenCalledWith('posthog')
    })

    it('reports unavailable (with the resolve reason) when no link can be minted', async () => {
        const relink = vi.fn(async () => null)
        const resolve = vi.fn(async () => ({
            kind: 'unavailable',
            provider: 'posthog',
            reason: 'shared_session_unsupported',
        }))
        const res = await identityConnectV1.run({ provider: 'posthog' }, ctx({ relink, resolve: resolve as never }))
        expect(res).toEqual({ unavailable: { provider: 'posthog', reason: 'shared_session_unsupported' } })
    })

    it('reports unavailable when the agent has no identity surface at all', async () => {
        const res = await identityConnectV1.run({ provider: 'posthog' }, ctx(undefined))
        expect(res.unavailable?.provider).toBe('posthog')
        expect(res.authorize_url).toBeUndefined()
    })
})
