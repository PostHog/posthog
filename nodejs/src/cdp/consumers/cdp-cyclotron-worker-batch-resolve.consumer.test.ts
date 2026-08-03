import { Team } from '~/types'

import { CyclotronJobInvocationHogFlow } from '../types'
import { buildAccountHogFlowInvocation } from './cdp-cyclotron-worker-batch-resolve.consumer'

describe('buildAccountHogFlowInvocation', () => {
    const team = { id: 123, name: 'Test team' } as Team

    it('carries the account group key and no person', () => {
        const invocation = buildAccountHogFlowInvocation({
            siteUrl: 'https://us.posthog.com',
            parentRunId: 'batch-job-1',
            team,
            hogFlowId: 'flow-1',
            externalId: 'acme-1',
            groupType: 'customer',
            defaultVariables: { greeting: 'hi' },
        })

        const state = invocation.state as CyclotronJobInvocationHogFlow['state']

        expect(state.event.event).toEqual('$batch_hog_flow_invocation')
        // distinct_id doubles as the per-account key for invocation_results; it must NOT
        // resolve to a person (the hogflow worker skips the lookup for account audiences).
        expect(state.event.distinct_id).toEqual('acme-1')
        expect(state.event.properties['$groups']).toEqual({ customer: 'acme-1' })
        expect(state.personId).toBeUndefined()
        // The stamp is what the hogflow worker trusts when the live trigger has been
        // edited to a person audience while these children were still queued.
        expect(state.accountAudience).toBe(true)
        expect(state.variables).toEqual({ greeting: 'hi' })
        expect(invocation.parentRunId).toEqual('batch-job-1')
        expect(invocation.queue).toEqual('hogflow')
        expect((invocation as any).person).toBeUndefined()
    })
})
