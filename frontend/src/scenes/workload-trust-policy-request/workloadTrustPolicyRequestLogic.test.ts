import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workloadTrustPolicyRequestLogic } from './workloadTrustPolicyRequestLogic'

const REQUEST = {
    id: 'request-1',
    name: 'Production deploys',
    status: 'pending',
    can_approve: true,
    approvers: [],
    scopes: ['query:read'],
    risky_scopes: {},
}

describe('workloadTrustPolicyRequestLogic', () => {
    let approvalBodies: string[]

    beforeEach(() => {
        approvalBodies = []
        initKeaTests()
    })

    it.each([
        [
            'a custom issuer sends the typed host',
            'auth.example.com',
            'auth.example.com',
            '{"confirm_issuer_host":"auth.example.com"}',
        ],
        ['a custom issuer waits for the exact host', 'auth.example.com', 'auth.example', null],
        ['a supported provider needs no host', null, '', ''],
    ])('approving %s', async (_name, confirmIssuerHost, typed, sentBody) => {
        useMocks({
            get: {
                '/api/projects/:team_id/workload_trust_policy_requests/:id/': {
                    ...REQUEST,
                    confirm_issuer_host: confirmIssuerHost,
                },
            },
            post: {
                '/api/projects/:team_id/workload_trust_policy_requests/:id/approve/': async ({ request }) => {
                    approvalBodies.push(await request.text())
                    return [200, { ...REQUEST, status: 'approved', confirm_issuer_host: confirmIssuerHost }]
                },
            },
        })
        const logic = workloadTrustPolicyRequestLogic({ id: 'request-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setConfirmIssuerHost(typed)

        expect(logic.values.issuerHostConfirmed).toBe(sentBody !== null)
        if (sentBody !== null) {
            logic.actions.approve()
            await expectLogic(logic).toFinishAllListeners()

            expect(approvalBodies).toEqual([sentBody])
        }
    })
})
