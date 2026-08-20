import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import posthog from 'posthog-js'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { AddIntegrationButton } from './AddIntegrationButton'

jest.mock('posthog-js')

// SourceIcon carries its own kea logic and isn't under test — the rows still render their labels.
jest.mock('products/data_warehouse/frontend/shared/components/SourceIcon', () => ({
    SourceIcon: (): null => null,
}))

describe('<AddIntegrationButton />', () => {
    const mountAsMember = (level: OrganizationMembershipLevel): void => {
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess(MOCK_DEFAULT_ORGANIZATION)
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, effective_membership_level: level })
    }

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    afterEach(() => {
        cleanup()
    })

    it('offers no selectable source when the user is not a project admin', async () => {
        mountAsMember(OrganizationMembershipLevel.Member)
        render(<AddIntegrationButton />)

        expect(screen.getByText('Add source').closest('button')).toHaveAttribute('aria-disabled', 'true')

        // The disabled trigger must not open a menu of un-selectable rows — those are what users dead-click.
        await userEvent.click(screen.getByText('Add source'))
        expect(screen.queryByText('BigQuery')).not.toBeInTheDocument()
    })

    it('lets a project admin pick a source and records the click', async () => {
        mountAsMember(OrganizationMembershipLevel.Admin)
        render(<AddIntegrationButton />)

        await userEvent.click(screen.getByText('Add source'))

        const source = screen.getByText('BigQuery').closest('button')
        expect(source).not.toHaveAttribute('aria-disabled', 'true')

        await userEvent.click(source!)
        expect(posthog.capture).toHaveBeenCalledWith('warehouse new source selected', {
            kind: 'BigQuery',
            from: 'marketing analytics',
        })
    })
})
