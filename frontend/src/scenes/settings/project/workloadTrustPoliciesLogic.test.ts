import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { workloadTrustPoliciesLogic } from './workloadTrustPoliciesLogic'

describe('workloadTrustPoliciesLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('forgets a subject lookup when another policy opens', async () => {
        const logic = workloadTrustPoliciesLogic()
        logic.mount()
        logic.actions.lookUpSubjectSuccess({ subject: '1234', subject_name: 'acme/web', found_via: 'GitHub' })

        await expectLogic(logic, () => {
            logic.actions.setEditingPolicyId('new')
        }).toMatchValues({ subjectLookup: null })
    })
})
