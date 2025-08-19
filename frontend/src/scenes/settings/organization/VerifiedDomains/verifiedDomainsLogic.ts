import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { SECURE_URL_REGEX } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, OrganizationDomainType } from '~/types'

import type { verifiedDomainsLogicType } from './verifiedDomainsLogicType'

export type OrganizationDomainUpdatePayload = Partial<
    Pick<OrganizationDomainType, 'jit_provisioning_enabled' | 'sso_enforcement'>
> &
    Pick<OrganizationDomainType, 'id'>

export type SAMLConfigType = Partial<
    Pick<OrganizationDomainType, 'saml_acs_url' | 'saml_entity_id' | 'saml_x509_cert'> &
        Pick<OrganizationDomainType, 'id'>
>

export const isSecureURL = (url: string): boolean => {
    try {
        const parsed = new URL(url)
        return parsed.protocol === 'https:'
    } catch {
        return false
    }
}

export const verifiedDomainsLogic = kea<verifiedDomainsLogicType>([
    path(['scenes', 'organization', 'verifiedDomainsLogic']),
    connect(() => ({ values: [organizationLogic, ['currentOrganization']], logic: [userLogic] })),
    actions({
        replaceDomain: (domain: OrganizationDomainType) => ({ domain }),
        setAddModalShown: (shown: boolean) => ({ shown }),
        setConfigureSAMLModalId: (id: string | null) => ({ id }),
        setVerifyModal: (id: string | null) => ({ id }),
    }),
    reducers({
        verifiedDomains: [
            [] as OrganizationDomainType[],
            {
                replaceDomain: (state, { domain }) => {
                    const domains: OrganizationDomainType[] = [...state.filter(({ id }) => id !== domain.id), domain]
                    domains.sort((a, b) => a.domain.localeCompare(b.domain))
                    return domains
                },
            },
        ],
        addModalShown: [
            false,
            {
                setAddModalShown: (_, { shown }) => shown,
                addVerifiedDomainSuccess: () => false,
            },
        ],
        configureSAMLModalId: [
            null as null | string,
            {
                setConfigureSAMLModalId: (_, { id }) => id,
            },
        ],
        verifyModal: [
            null as string | null,
            {
                setVerifyModal: (_, { id }) => id,
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        verifiedDomains: [
            [] as OrganizationDomainType[],
            {
                loadVerifiedDomains: async () =>
                    (await api.get(`api/organizations/${values.currentOrganization?.id}/domains`))
                        .results as OrganizationDomainType[],
                addVerifiedDomain: async (domain: string) => {
                    const response = await api.create<OrganizationDomainType>(
                        `api/organizations/${values.currentOrganization?.id}/domains`,
                        {
                            domain,
                        }
                    )
                    return [response, ...values.verifiedDomains]
                },
                deleteVerifiedDomain: async (id: string) => {
                    await api.delete(`api/organizations/${values.currentOrganization?.id}/domains/${id}`)
                    return values.verifiedDomains.filter((domain) => domain.id !== id)
                },
            },
        ],
        updatingDomain: [
            false,
            {
                updateDomain: async (payload: OrganizationDomainUpdatePayload) => {
                    const response = await api.update<OrganizationDomainType>(
                        `api/organizations/${values.currentOrganization?.id}/domains/${payload.id}`,
                        { ...payload, id: undefined }
                    )
                    lemonToast.success('Domain updated successfully! Changes will take immediately.')
                    actions.replaceDomain(response)
                    return false
                },
                verifyDomain: async () => {
                    const response = await api.create<OrganizationDomainType>(
                        `api/organizations/${values.currentOrganization?.id}/domains/${values.verifyModal}/verify`
                    )
                    if (response.is_verified) {
                        lemonToast.success('Domain verified successfully.')
                    } else {
                        lemonToast.warning(
                            'We could not verify your domain yet. DNS propagation may take up to 72 hours. Please try again later.'
                        )
                    }
                    actions.replaceDomain(response)
                    actions.setVerifyModal(null)
                    return false
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setConfigureSAMLModalId: ({ id }) => {
            const domain = values.verifiedDomains.find(({ id: _idToFind }) => _idToFind === id)
            if (id && domain) {
                const { saml_acs_url, saml_entity_id, saml_x509_cert } = domain
                actions.setSamlConfigValues({ saml_acs_url, saml_entity_id, saml_x509_cert, id })
            }
        },
    })),
    selectors({
        domainBeingVerified: [
            (s) => [s.verifiedDomains, s.verifyModal],
            (verifiedDomains, verifyingId): OrganizationDomainType | null =>
                (verifyingId && verifiedDomains.find(({ id }) => id === verifyingId)) || null,
        ],
        isSSOEnforcementAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.SSO_ENFORCEMENT),
        ],
        isSAMLAvailable: [
            () => [userLogic.selectors.hasAvailableFeature],
            (hasAvailableFeature): boolean => hasAvailableFeature(AvailableFeature.SAML),
        ],
    }),
    afterMount(({ actions }) => actions.loadVerifiedDomains()),
    forms(({ actions, values }) => ({
        samlConfig: {
            defaults: {} as SAMLConfigType,
            errors: (payload) => ({
                saml_acs_url:
                    payload.saml_acs_url && !payload.saml_acs_url.match(SECURE_URL_REGEX)
                        ? 'Please enter a valid URL, including https://'
                        : undefined,
            }),
            submit: async (payload, breakpoint) => {
                const { id, ...updateParams } = payload
                if (!id) {
                    return
                }
                const response = await api.update<OrganizationDomainType>(
                    `api/organizations/${values.currentOrganization?.id}/domains/${payload.id}`,
                    {
                        ...updateParams,
                    }
                )
                breakpoint()
                actions.replaceDomain(response)
                actions.setConfigureSAMLModalId(null)
                actions.setSamlConfigValues({})
                lemonToast.success(`SAML configuration for ${response.domain} updated successfully.`)
            },
        },
    })),
])
