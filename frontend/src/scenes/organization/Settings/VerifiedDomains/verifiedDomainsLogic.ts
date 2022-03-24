import { kea } from 'kea'
import api from 'lib/api'
import { lemonToast } from 'lib/components/lemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationDomainType, AvailableFeature } from '~/types'
import { verifiedDomainsLogicType } from './verifiedDomainsLogicType'

type OrganizationDomainUpdatePayload = Partial<
    Pick<OrganizationDomainType, 'jit_provisioning_enabled' | 'sso_enforcement'>
> &
    Pick<OrganizationDomainType, 'id'>

export const verifiedDomainsLogic = kea<verifiedDomainsLogicType<OrganizationDomainUpdatePayload>>({
    path: ['scenes', 'organization', 'verifiedDomainsLogic'],
    connect: {
        values: [organizationLogic, ['currentOrganization']],
    },
    actions: {
        replaceDomain: (domain: OrganizationDomainType) => ({ domain }),
        setAddModalShown: (shown: boolean) => ({ shown }),
        setVerifyModal: (id: string | null) => ({ id }),
    },
    reducers: {
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
        verifyModal: [
            null as string | null,
            {
                setVerifyModal: (_, { id }) => id,
            },
        ],
    },
    loaders: ({ values, actions }) => ({
        verifiedDomains: [
            [] as OrganizationDomainType[],
            {
                loadVerifiedDomains: async () =>
                    (await api.get(`api/organizations/${values.currentOrganization?.id}/domains`))
                        .results as OrganizationDomainType[],
                addVerifiedDomain: async (domain: string) => {
                    const response = await api.create(`api/organizations/${values.currentOrganization?.id}/domains`, {
                        domain,
                    })
                    return [response, ...values.verifiedDomains]
                },
                deleteVerifiedDomain: async (id: string) => {
                    await api.delete(`api/organizations/${values.currentOrganization?.id}/domains/${id}`)
                    return [...values.verifiedDomains.filter((domain) => domain.id !== id)]
                },
            },
        ],
        updatingDomain: [
            false,
            {
                updateDomain: async (payload: OrganizationDomainUpdatePayload) => {
                    const response = await api.update(
                        `api/organizations/${values.currentOrganization?.id}/domains/${payload.id}`,
                        { ...payload, id: undefined }
                    )
                    lemonToast.success('Domain updated successfully! Changes will take immediately.')
                    actions.replaceDomain(response as OrganizationDomainType)
                    return false
                },
                verifyDomain: async () => {
                    const response = (await api.create(
                        `api/organizations/${values.currentOrganization?.id}/domains/${values.verifyModal}/verify`
                    )) as OrganizationDomainType
                    if (response.is_verified) {
                        lemonToast.success('Domain verified successfully.')
                    } else {
                        lemonToast.warning(
                            'We could not verify your domain yet. DNS propagation may take up to 72 hours. Please try again later.'
                        )
                    }
                    actions.replaceDomain(response as OrganizationDomainType)
                    actions.setVerifyModal(null)
                    return false
                },
            },
        ],
    }),
    selectors: {
        domainBeingVerified: [
            (s) => [s.verifiedDomains, s.verifyModal],
            (verifiedDomains, verifyingId): OrganizationDomainType | null =>
                (verifyingId && verifiedDomains.find(({ id }) => id === verifyingId)) || null,
        ],
        isSSOEnforcementAvailable: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean =>
                currentOrganization?.available_features.includes(AvailableFeature.SSO_ENFORCEMENT) ?? false,
        ],
        isFeatureAvailable: [
            (s) => [s.currentOrganization, s.isSSOEnforcementAvailable],
            (currentOrganization, isSSOEnforcementAvailable): boolean =>
                (isSSOEnforcementAvailable ||
                    currentOrganization?.available_features.includes(AvailableFeature.SAML)) ??
                false,
        ],
    },
    events: ({ actions }) => ({
        afterMount: [actions.loadVerifiedDomains],
    }),
})
