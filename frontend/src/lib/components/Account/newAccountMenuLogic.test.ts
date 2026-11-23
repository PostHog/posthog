import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { initKeaTests } from '~/test/init'

import { newAccountMenuLogic, ProjectListItem } from './newAccountMenuLogic'

describe('newAccountMenuLogic', () => {
    it("gives each project row its own project's logo", () => {
        const otherTeam = { ...MOCK_DEFAULT_TEAM, id: 2, project_id: 2, name: 'Other' }
        const noLogoTeam = { ...MOCK_DEFAULT_TEAM, id: 3, project_id: 3, name: 'No logo' }
        initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
            ...MOCK_DEFAULT_ORGANIZATION,
            teams: [MOCK_DEFAULT_TEAM, otherTeam, noLogoTeam],
            projects: [
                { ...MOCK_DEFAULT_PROJECT, logo_media_id: 'current-logo' },
                { id: 2, organization_id: MOCK_DEFAULT_ORGANIZATION.id, name: 'Other', logo_media_id: 'other-logo' },
                { id: 3, organization_id: MOCK_DEFAULT_ORGANIZATION.id, name: 'No logo' },
            ],
        })
        const logic = newAccountMenuLogic()
        logic.mount()

        const logos = Object.fromEntries(
            logic.values.filteredProjectItems
                .filter((item): item is ProjectListItem => item.type === 'project')
                .map((item) => [item.team.name, item.logoMediaId])
        )
        expect(logos).toEqual({
            [MOCK_DEFAULT_TEAM.name]: 'current-logo',
            Other: 'other-logo',
            'No logo': null,
        })
    })
})
