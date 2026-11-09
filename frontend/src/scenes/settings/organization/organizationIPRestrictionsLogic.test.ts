import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { organizationLogic, OrganizationUpdatePayload } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import { organizationIPRestrictionsLogic } from './organizationIPRestrictionsLogic'

const organization = { ...MOCK_DEFAULT_ORGANIZATION, ip_restrictions: ['203.0.113.4'] }
const draft = [...organization.ip_restrictions, '198.51.100.7']

describe('organizationIPRestrictionsLogic', () => {
    let logic: ReturnType<typeof organizationIPRestrictionsLogic.build>

    beforeEach(() => {
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, organization)
        logic = organizationIPRestrictionsLogic()
        logic.mount()
        logic.actions.setDraftEntries(draft, organization.id)
    })

    it.each<[string, OrganizationUpdatePayload | undefined]>([
        ['an MCP setting saves', { read_only_mcp_access: true }],
        ['enforcement is disabled', { ip_restrictions_enabled: false }],
        ['the same organization reloads', undefined],
    ])('preserves pending rules when %s', async (_, payload) => {
        await expectLogic(logic, () => {
            if (payload) {
                organizationLogic.actions.updateOrganizationSuccess({ ...organization, ...payload }, payload)
            } else {
                organizationLogic.actions.loadCurrentOrganizationSuccess({ ...organization })
            }
        }).toMatchValues({ values: draft, isDirty: true })
    })

    it('uses the saved rules after an IP-list save succeeds', async () => {
        await expectLogic(logic, () => {
            organizationLogic.actions.updateOrganizationSuccess(
                { ...organization, ip_restrictions: draft },
                { ip_restrictions: draft }
            )
        }).toMatchValues({ values: draft, draftEntries: null, isDirty: false })
    })

    it.each(['reload', 'update'])('discards the previous organization draft on an organization %s', async (event) => {
        const nextOrganization = { ...organization, id: 'another-organization', ip_restrictions: ['198.51.100.12'] }
        await expectLogic(logic, () => {
            if (event === 'reload') {
                organizationLogic.actions.loadCurrentOrganizationSuccess(nextOrganization)
            } else {
                organizationLogic.actions.updateOrganizationSuccess(nextOrganization, { name: 'Another organization' })
            }
        }).toMatchValues({ values: nextOrganization.ip_restrictions, isDirty: false })

        await expectLogic(logic, () => {
            organizationLogic.actions.loadCurrentOrganizationSuccess(organization)
        }).toMatchValues({ values: organization.ip_restrictions, isDirty: false })
    })
})
