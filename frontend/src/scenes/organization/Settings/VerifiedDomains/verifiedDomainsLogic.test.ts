import { verifiedDomainsLogic } from './verifiedDomainsLogic'
import { initKeaTests } from '~/test/init'
import { useAvailableFeatures } from '~/mocks/features'
import { AvailableFeature } from '~/types'
import { useMocks } from '~/mocks/jest'
import { expectLogic } from 'kea-test-utils'

describe('verifiedDomainsLogic', () => {
    let logic: ReturnType<typeof verifiedDomainsLogic.build>

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.SSO_ENFORCEMENT, AvailableFeature.SAML])
        useMocks({
            get: {
                '/api/organizations/:organization/domains': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '8db3b0c2-a0ab-490a-9037-14f3358a81bc',
                            domain: 'my.posthog.com',
                            jit_provisioning_enabled: true,
                            sso_enforcement: 'google-oauth2',
                            is_verified: true,
                            verified_at: '2022-01-01T23:59:59',
                        },
                        {
                            id: 'id_will_be_deleted',
                            domain: 'temp.posthog.com',
                            jit_provisioning_enabled: false,
                            sso_enforcement: '',
                            is_verified: false,
                            verified_at: '',
                        },
                    ],
                },
            },
            post: {
                '/api/organizations/:organization/domains/': {
                    id: '14f3358a-a0ab-490a-9037-81a0abc',
                    domain: 'new.posthog.com',
                    jit_provisioning_enabled: false,
                    sso_enforcement: '',
                    is_verified: false,
                    verified_at: '',
                },
            },
            delete: {
                '/api/organizations/:organization/domains/:id/': {},
            },
        })
        initKeaTests()
        logic = verifiedDomainsLogic()
        logic.mount()
    })

    describe('values', () => {
        it('has proper defaults', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values).toMatchSnapshot()
        })

        it('creates domain correctly', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.addVerifiedDomain('new.posthog.com')
            await expectLogic(logic).toFinishAllListeners()
            const { verifiedDomains } = logic.values
            expect(verifiedDomains.length).toEqual(3)
            expect(verifiedDomains[0].domain).toEqual('new.posthog.com') // added at the top
        })

        it('deletes domain correctly', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.deleteVerifiedDomain('id_will_be_deleted')
            await expectLogic(logic).toFinishAllListeners()
            const { verifiedDomains } = logic.values
            expect(verifiedDomains.length).toEqual(1)
        })
    })
})
