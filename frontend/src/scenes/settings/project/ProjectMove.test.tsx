import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { OrganizationMembershipLevel } from 'lib/constants'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { OrganizationBasicType } from '~/types'

import { ProjectMove } from './ProjectMove'

// Render LemonSelect as a native <select> so each option's disabled state is assertable from the DOM
// without driving the (portal-rendered) popover. We only override LemonSelect; the other Lemon components stay real.
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonSelect: ({ options, value, onChange, placeholder }: any): JSX.Element => (
        <select
            aria-label="target organization"
            value={value === undefined ? '' : String(value)}
            onChange={(e) => onChange?.(options.find((o: any) => String(o.value) === e.target.value)?.value)}
        >
            <option value="">{placeholder}</option>
            {options.map((o: any) => (
                <option key={String(o.value)} value={String(o.value)} disabled={!!o.disabledReason}>
                    {o.label}
                </option>
            ))}
        </select>
    ),
}))

const targetOrg = (overrides: Partial<OrganizationBasicType>): OrganizationBasicType => ({
    ...MOCK_DEFAULT_ORGANIZATION,
    ...overrides,
})

describe('<ProjectMove />', () => {
    const adminTargetOrg = targetOrg({
        id: 'org-admin',
        name: 'Admin Target Org',
        membership_level: OrganizationMembershipLevel.Admin,
    })
    const memberTargetOrg = targetOrg({
        id: 'org-member',
        name: 'Member Target Org',
        membership_level: OrganizationMembershipLevel.Member,
    })

    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
        teamLogic.mount()
        projectLogic.mount()
        // Admin of the current team so the source-org guard (`restrictedReason`) passes and the target guard is what's under test.
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Admin,
        })
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            organization: MOCK_DEFAULT_ORGANIZATION,
            organizations: [MOCK_DEFAULT_ORGANIZATION, adminTargetOrg, memberTargetOrg],
        })
        projectLogic.actions.loadCurrentProjectSuccess({ id: 1, name: 'Source Project' } as any)
    })

    afterEach(() => {
        cleanup()
    })

    it('disables target organizations the user is not an admin of', () => {
        const { container } = render(<ProjectMove />)
        expect(screen.getByRole('option', { name: 'Admin Target Org' })).toBeEnabled()
        expect(screen.getByRole('option', { name: 'Member Target Org' })).toBeDisabled()
        // No org picked yet, so the Move button is blocked.
        expect(container.querySelector('[data-attr="move-project-button"]')).toHaveAttribute('aria-disabled', 'true')
    })

    it('enables the Move button once an admin-eligible target org is selected', async () => {
        const { container } = render(<ProjectMove />)
        await userEvent.selectOptions(screen.getByLabelText('target organization'), 'org-admin')
        expect(container.querySelector('[data-attr="move-project-button"]')).toHaveAttribute('aria-disabled', 'false')
    })
})
