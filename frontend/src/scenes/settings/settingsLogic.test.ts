import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { partnerBillingApplicationsLogic } from 'products/billing/frontend/partnerBilling/partnerBillingApplicationsLogic'

import { settingsLogic } from './settingsLogic'

const PARTNER_APPLICATION = { id: '0192d7c4-5b6e-7000-8000-00000000a001', name: 'Example Partner', logo_uri: null }

describe('settingsLogic', () => {
    it.each([
        ['has a paying partner application', [PARTNER_APPLICATION], { reachable: true, listed: true }],
        ['has no paying partner application', [], { reachable: false, listed: false }],
    ])('shows partner billing only when the organization %s', async (_name, applications, expected) => {
        let answerApplications: () => void = () => {}
        const applicationsAnswered = new Promise<void>((resolve) => {
            answerApplications = resolve
        })
        useMocks({
            get: {
                '/api/organizations/:organization_id/partner_billing/': async () => {
                    await applicationsAnswered
                    return [200, applications]
                },
            },
        })
        initKeaTests()
        const logic = settingsLogic({ logicKey: 'test' })
        logic.mount()
        const partnerBillingIn = (sections: { id: string }[]): boolean =>
            sections.some((section) => section.id === 'organization-partner-billing')

        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        expect({
            reachable: partnerBillingIn(logic.values.sections),
            listed: partnerBillingIn(logic.values.filteredSections),
        }).toEqual({ reachable: true, listed: false })

        answerApplications()
        await expectLogic(partnerBillingApplicationsLogic).toDispatchActions(['loadPartnerBillingApplicationsSuccess'])
        expect({
            reachable: partnerBillingIn(logic.values.sections),
            listed: partnerBillingIn(logic.values.filteredSections),
        }).toEqual(expected)

        logic.unmount()
    })
})
