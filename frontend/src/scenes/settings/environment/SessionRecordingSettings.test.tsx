import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { getByDataAttr } from '~/test/byDataAttr'
import { initKeaTests } from '~/test/init'
import { OrganizationType } from '~/types'

import { ReplayDataRetentionSettings } from './SessionRecordingSettings'

describe('<ReplayDataRetentionSettings /> locked retention options', () => {
    const mountSettings = (teamOverrides?: Partial<typeof MOCK_DEFAULT_TEAM>): void => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, ...teamOverrides })
        userLogic.mount()
        teamLogic.mount()
        organizationLogic.mount()
    }

    const loadOrganization = (overrides: Partial<OrganizationType>): void => {
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...organizationLogic.values.currentOrganization,
            ...overrides,
        } as any)
    }

    afterEach(cleanup)

    it.each([
        'session-recording-retention-button-90d',
        'session-recording-retention-button-1y',
        'session-recording-retention-button-5y',
    ])('opens billing on the platform packages for a locked option: %s', async (dataAttr) => {
        mountSettings()
        loadOrganization({ membership_level: OrganizationMembershipLevel.Admin })

        render(<ReplayDataRetentionSettings />)

        await userEvent.click(getByDataAttr(document.body, dataAttr))

        expect(router.values.location.pathname).toBe('/organization/billing')
        expect(router.values.location.search).toBe('?products=platform_and_support')
    })

    it('does not navigate from a locked option while the area is restricted', async () => {
        mountSettings({ effective_membership_level: OrganizationMembershipLevel.Member })
        loadOrganization({ membership_level: OrganizationMembershipLevel.Member })

        render(<ReplayDataRetentionSettings />)

        await userEvent.click(getByDataAttr(document.body, 'session-recording-retention-button-5y'))

        expect(router.values.location.pathname).not.toBe('/organization/billing')
    })

    it('does not navigate from a locked option while organization settings are loading', () => {
        mountSettings()
        organizationLogic.actions.loadCurrentOrganization()

        render(<ReplayDataRetentionSettings />)

        fireEvent.click(getByDataAttr(document.body, 'session-recording-retention-button-90d'))

        expect(router.values.location.pathname).not.toBe('/organization/billing')
    })
})
