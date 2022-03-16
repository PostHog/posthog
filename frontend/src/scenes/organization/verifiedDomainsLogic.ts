import { kea } from 'kea'
import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'
import { OrganizationDomainType } from '~/types'
import { verifiedDomainsLogicType } from './verifiedDomainsLogicType'

export const verifiedDomainsLogic = kea<verifiedDomainsLogicType>({
    path: ['scenes', 'organization', 'verifiedDomainsLogic'],
    connect: {
        values: [organizationLogic, ['currentOrganization']],
    },
    loaders: ({ values }) => ({
        verifiedDomains: [
            [] as OrganizationDomainType[],
            {
                loadVerifiedDomains: async () =>
                    (await api.get(`api/organizations/${values.currentOrganization?.id}/domains`))
                        .results as OrganizationDomainType[],
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadVerifiedDomains],
    }),
})
