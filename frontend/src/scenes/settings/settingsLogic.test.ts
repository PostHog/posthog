import { expectLogic } from 'kea-test-utils'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { partnerBillingApplicationsLogic } from 'products/billing/frontend/partnerBilling/partnerBillingApplicationsLogic'

import { settingsLogic } from './settingsLogic'

const PARTNER_APPLICATIONS_URL = '/api/organizations/:organization_id/partner_billing/'
const PARTNER_APPLICATION = { id: '0192d7c4-5b6e-7000-8000-00000000a001', name: 'Example Partner', logo_uri: null }

describe('settingsLogic', () => {
    let applicationRequests: number
    let answerApplications: () => void

    const heldApplicationsResponse = (response: [number, unknown]): (() => Promise<[number, unknown]>) => {
        applicationRequests = 0
        const applicationsAnswered = new Promise<void>((resolve) => {
            answerApplications = resolve
        })
        return async () => {
            applicationRequests += 1
            await applicationsAnswered
            return response
        }
    }

    const partnerBillingIn = (sections: { id: string }[]): boolean =>
        sections.some((section) => section.id === 'organization-partner-billing')

    it.each<[string, [number, unknown], string, { reachable: boolean; listed: boolean }]>([
        [
            'has a paying partner application',
            [200, [PARTNER_APPLICATION]],
            'loadPartnerBillingApplicationsSuccess',
            { reachable: true, listed: true },
        ],
        [
            'has no paying partner application',
            [200, []],
            'loadPartnerBillingApplicationsSuccess',
            { reachable: false, listed: false },
        ],
        [
            'could not load its partner applications',
            [500, { detail: 'Server error' }],
            'loadPartnerBillingApplicationsFailure',
            { reachable: true, listed: true },
        ],
    ])(
        'in the settings scene, shows partner billing when the organization %s',
        async (_name, response, answeredAction, expected) => {
            useMocks({ get: { [PARTNER_APPLICATIONS_URL]: heldApplicationsResponse(response) } })
            initKeaTests()
            const logic = settingsLogic({ logicKey: 'settingsScene' })
            logic.mount()

            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            expect({
                reachable: partnerBillingIn(logic.values.sections),
                listed: partnerBillingIn(logic.values.filteredSections),
            }).toEqual({ reachable: true, listed: false })

            answerApplications()
            await expectLogic(partnerBillingApplicationsLogic).toDispatchActions([answeredAction])
            expect({
                reachable: partnerBillingIn(logic.values.sections),
                listed: partnerBillingIn(logic.values.filteredSections),
            }).toEqual(expected)

            logic.unmount()
        }
    )

    it('does not ask for the partner application list in a scene that embeds one section', async () => {
        useMocks({ get: { [PARTNER_APPLICATIONS_URL]: heldApplicationsResponse([200, [PARTNER_APPLICATION]]) } })
        initKeaTests()
        const logic = settingsLogic({
            logicKey: 'errorTracking',
            sectionId: 'environment-error-tracking-configuration',
            settingId: 'error-tracking-alerting',
        })
        logic.mount()
        answerApplications()

        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        await expectLogic(partnerBillingApplicationsLogic).toFinishAllListeners()

        expect(applicationRequests).toEqual(0)
        logic.unmount()
    })
})
