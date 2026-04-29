import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { OrganizationType } from '~/types'

import { organizationLogic } from '../../organizationLogic'
import { GuestResourcePicker } from './GuestResourcePicker'
import { inviteLogic } from './inviteLogic'

const TEAM_MARKETING = { id: 997, name: 'Marketing' }
const TEAM_PRODUCT = { id: 998, name: 'Product' }

function mountWithOrgTeams(teams: { id: number; name: string }[]): void {
    const organization: Partial<OrganizationType> = {
        id: 'org-1',
        name: 'Acme',
        slug: 'acme',
        membership_level: 15,
        teams: teams as any,
        member_count: 1,
        metadata: {} as any,
    }
    organizationLogic.mount()
    organizationLogic.actions.loadCurrentOrganizationSuccess(organization as OrganizationType)
    inviteLogic.mount()
    inviteLogic.actions.setIsGuestInvite(true)
}

describe('GuestResourcePicker', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/notebooks/': () => [
                    200,
                    { results: [{ id: 1, short_id: 'NB000001', title: 'Onboarding playbook' }] },
                ],
            },
        })
        initKeaTests()
    })

    it('hides the project picker for a single-project org', () => {
        mountWithOrgTeams([TEAM_MARKETING])
        render(<GuestResourcePicker />)
        expect(document.querySelector('[data-attr="guest-resource-project-picker"]')).toBeNull()
    })

    it('renders the project picker for a multi-project org and defaults to currentTeamId', async () => {
        mountWithOrgTeams([TEAM_MARKETING, TEAM_PRODUCT])
        render(<GuestResourcePicker />)
        const picker = document.querySelector('[data-attr="guest-resource-project-picker"]') as HTMLElement | null
        expect(picker).not.toBeNull()
        // Default current team is MOCK_TEAM_ID = 997 (Marketing)
        await waitFor(() => expect(picker?.textContent).toContain('Marketing'))
    })

    it('switching the project picker fetches resources from the new project', async () => {
        const fetchedTeamIds: number[] = []
        useMocks({
            get: {
                '/api/projects/:team/notebooks/': (req) => {
                    fetchedTeamIds.push(Number(req.params.team))
                    return [200, { results: [] }]
                },
            },
        })
        mountWithOrgTeams([TEAM_MARKETING, TEAM_PRODUCT])
        render(<GuestResourcePicker />)

        // Initial fetch — defaults to currentTeamId (Marketing).
        await waitFor(() => expect(fetchedTeamIds).toContain(TEAM_MARKETING.id))

        const picker = document.querySelector('[data-attr="guest-resource-project-picker"]') as HTMLElement
        await userEvent.click(picker)
        const productOption = (await screen.findAllByRole('menuitem')).find((el) => el.textContent === 'Product')!
        await userEvent.click(productOption)

        // Switching the picker triggers a fetch keyed on the new project's team_id.
        await waitFor(() => expect(fetchedTeamIds).toContain(TEAM_PRODUCT.id))
    })

    it('groups the Selected list by project with project-name headers', async () => {
        mountWithOrgTeams([TEAM_MARKETING, TEAM_PRODUCT])
        render(<GuestResourcePicker />)

        inviteLogic.actions.addGuestGrant({
            team_id: TEAM_MARKETING.id,
            resource: 'notebook',
            resource_id: 'NB000001',
            label: 'Marketing notebook',
        })
        inviteLogic.actions.addGuestGrant({
            team_id: TEAM_PRODUCT.id,
            resource: 'notebook',
            resource_id: 'NB000002',
            label: 'Onboarding notebook',
        })

        await waitFor(() => {
            expect(document.querySelector(`[data-attr="guest-grants-group-${TEAM_MARKETING.id}"]`)).not.toBeNull()
            expect(document.querySelector(`[data-attr="guest-grants-group-${TEAM_PRODUCT.id}"]`)).not.toBeNull()
        })
        const marketingGroup = document.querySelector(
            `[data-attr="guest-grants-group-${TEAM_MARKETING.id}"]`
        ) as HTMLElement
        const productGroup = document.querySelector(
            `[data-attr="guest-grants-group-${TEAM_PRODUCT.id}"]`
        ) as HTMLElement
        expect(marketingGroup.textContent).toContain('Marketing')
        expect(marketingGroup.textContent).toContain('Marketing notebook')
        expect(productGroup.textContent).toContain('Product')
        expect(productGroup.textContent).toContain('Onboarding notebook')
    })
})
