import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature } from '~/types'

import { isSecureURL, verifiedDomainsLogic } from './verifiedDomainsLogic'

describe('verifiedDomainsLogic', () => {
    let logic: ReturnType<typeof verifiedDomainsLogic.build>
    let userlogic: ReturnType<typeof userLogic.build>

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
                '/api/organizations/:organization/identity_provider_configs/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 'saml-config-id',
                            name: 'Shared Okta',
                            has_saml: true,
                            has_scim: false,
                            has_id_jag: false,
                            saml_entity_id: 'okta-entity',
                            saml_acs_url: 'https://okta.example.com/sso',
                            saml_x509_cert: 'certificate',
                            scim_enabled: false,
                            scim_bearer_token: null,
                            id_jag_allowed_clients: [],
                            saml_domain_ids: ['8db3b0c2-a0ab-490a-9037-14f3358a81bc'],
                            scim_domain_ids: [],
                            id_jag_domain_ids: [],
                            created_at: '2022-01-01T23:59:59',
                            updated_at: '2022-01-01T23:59:59',
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
        userlogic = userLogic()
        userlogic.mount()
        logic.mount()
    })

    describe('isSecureURL', () => {
        it('should return true for an https URL', () => {
            expect(isSecureURL('https://www.example.com')).toEqual(true)
            expect(isSecureURL('https://www.example.com/pathname?query=true#hash')).toEqual(true)
            expect(isSecureURL('https://localhost:8080')).toEqual(true)
            expect(isSecureURL('https://localhost:8080/pathname?query=true#hash')).toEqual(true)

            expect(isSecureURL('http://www.example.com')).toEqual(false)
            expect(isSecureURL('http://www.example.com/pathname?query=true#hash')).toEqual(false)
            expect(isSecureURL('http://localhost:8080')).toEqual(false)
            expect(isSecureURL('http://localhost:8080/pathname?query=true#hash')).toEqual(false)

            expect(isSecureURL('www.example.com')).toEqual(false)
            expect(isSecureURL('www.example.com/pathname?query=true#hash')).toEqual(false)
            expect(isSecureURL('localhost:8080')).toEqual(false)
            expect(isSecureURL('localhost:8080/pathname?query=true#hash')).toEqual(false)

            expect(isSecureURL('notadomainorurl')).toEqual(false)
            expect(isSecureURL('123456')).toEqual(false)
        })
    })

    describe('values', () => {
        it('has proper defaults', async () => {
            await expectLogic(userlogic).toFinishAllListeners()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values).toMatchSnapshot()
        })

        it('creates domain correctly', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.addVerifiedDomain('new.posthog.com')
            await expectLogic(logic).toFinishAllListeners()
            const { verifiedDomains } = logic.values
            expect(verifiedDomains.length).toEqual(3)
            expect(verifiedDomains[2].domain).toEqual('new.posthog.com') // added at the end
        })

        it('deletes domain correctly', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.deleteVerifiedDomain('id_will_be_deleted')
            await expectLogic(logic).toFinishAllListeners()
            const { verifiedDomains } = logic.values
            expect(verifiedDomains.length).toEqual(1)
        })

        it('loads every assigned domain when editing a shared SAML config', async () => {
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setConfigureSAMLModalId('saml-config-id')
            expect(logic.values.samlConfig).toMatchObject({
                id: 'saml-config-id',
                name: 'Shared Okta',
                domain_ids: ['8db3b0c2-a0ab-490a-9037-14f3358a81bc'],
            })
        })
    })
})
