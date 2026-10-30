import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FeatureFlagType } from '~/types'

import { NEW_FLAG, featureFlagLogic } from './featureFlagLogic'
import FeatureFlagProjects from './FeatureFlagProjects'

const BULK_COPY_LINK_TEXT = 'bulk copy in the feature flags list'

const renderWithState = ({ teams, flag }: { teams: number; flag?: Partial<FeatureFlagType> }): void => {
    teamLogic.mount()
    teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
    organizationLogic.mount()
    organizationLogic.actions.loadCurrentOrganizationSuccess({
        ...MOCK_DEFAULT_ORGANIZATION,
        teams: Array.from({ length: teams }, (_, index) => ({
            ...MOCK_DEFAULT_TEAM,
            id: MOCK_DEFAULT_TEAM.id + index,
            project_id: MOCK_DEFAULT_TEAM.id + index,
            name: `Project ${index + 1}`,
        })),
    })
    featureFlagLogic.mount()
    featureFlagLogic.actions.loadFeatureFlagSuccess({
        ...NEW_FLAG,
        id: null,
        key: 'test-flag',
        ...flag,
    } as FeatureFlagType)

    render(<FeatureFlagProjects />)
}

describe('<FeatureFlagProjects />', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/feature_flags/:feature_flag_key': () => [200, []],
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    it('links to bulk copy in the flags list when the copy section renders', () => {
        renderWithState({ teams: 2 })

        expect(screen.getByText('Feature flag copy')).toBeInTheDocument()
        const link = screen.getByText(BULK_COPY_LINK_TEXT).closest('a')
        expect(link).not.toBeNull()
        // Link prefixes the current project path, so assert on the target itself
        expect(link?.getAttribute('href')).toMatch(/\/feature-flags\?tab=projects$/)
    })

    it('does not render the bulk copy link in a single-project organization', () => {
        renderWithState({ teams: 1 })

        expect(screen.queryByText('Feature flag copy')).not.toBeInTheDocument()
        expect(screen.queryByText(BULK_COPY_LINK_TEXT)).not.toBeInTheDocument()
    })

    it('does not render the bulk copy link when the flag cannot be edited', () => {
        renderWithState({ teams: 2, flag: { can_edit: false } })

        expect(screen.queryByText('Feature flag copy')).not.toBeInTheDocument()
        expect(screen.queryByText(BULK_COPY_LINK_TEXT)).not.toBeInTheDocument()
    })
})
