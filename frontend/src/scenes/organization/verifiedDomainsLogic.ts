import { kea } from 'kea'
import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationDomainType } from '~/types'
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
    },
    loaders: ({ values, actions }) => ({
        verifiedDomains: [
            [] as OrganizationDomainType[],
            {
                loadVerifiedDomains: async () =>
                    (await api.get(`api/organizations/${values.currentOrganization?.id}/domains`))
                        .results as OrganizationDomainType[],
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
                    actions.replaceDomain(response as OrganizationDomainType)
                    return true
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadVerifiedDomains],
    }),
})
