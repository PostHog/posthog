import { HogFlow } from '~/cdp/schema/hogflow'
import { Team } from '~/types'

import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { HOG_FLOW_MASK_EXAMPLES } from '../_tests/examples'
import { CyclotronJobInvocationHogFlow } from '../types'
import { buildAccountHogFlowInvocation } from './cdp-cyclotron-worker-batch-resolve.consumer'

describe('buildAccountHogFlowInvocation', () => {
    const team = { id: 123, name: 'Test team' } as Team
    // A non-default version, so the flowVersion assertion can't pass by accident.
    const hogFlow: HogFlow = { ...new FixtureHogFlowBuilder().withTeamId(team.id).build(), version: 4 }

    it('carries the account group key and no person', () => {
        const invocation = buildAccountHogFlowInvocation({
            siteUrl: 'https://us.posthog.com',
            parentRunId: 'batch-job-1',
            team,
            hogFlow,
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
        // Account broadcasts convert long after the send, so the run has to carry the version
        // that sent or the conversion is credited to whatever is published by then.
        expect(state.flowVersion).toBe(4)
        expect(state.variables).toEqual({ greeting: 'hi' })
        expect(invocation.parentRunId).toEqual('batch-job-1')
        expect(invocation.queue).toEqual('hogflow')
        expect((invocation as any).person).toBeUndefined()
    })

    // HogMaskerService.filterByMasking() only recognizes an invocation as a hog flow
    // invocation (and applies trigger_masking) when it carries a `hogFlow` object — if this
    // regresses, trigger_masking silently stops applying to batch-triggered runs again.
    it('attaches the hogFlow so trigger_masking can be applied by the batch resolver', () => {
        const maskedHogFlow: HogFlow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withTriggerMasking(HOG_FLOW_MASK_EXAMPLES.everyTime.trigger_masking)
            .build()

        const invocation = buildAccountHogFlowInvocation({
            siteUrl: 'https://us.posthog.com',
            parentRunId: 'batch-job-1',
            team,
            hogFlow: maskedHogFlow,
            externalId: 'acme-1',
            groupType: 'customer',
            defaultVariables: {},
        })

        expect(invocation.hogFlow).toBe(maskedHogFlow)
        expect(invocation.hogFlow.trigger_masking).toEqual(HOG_FLOW_MASK_EXAMPLES.everyTime.trigger_masking)
    })
})
