import { OrganizationFeatureFlag, OrganizationFeatureFlagRow } from '~/types'

import { cellStateFor } from './ProjectsGrid'

const CURRENT_TEAM_ID = 1
const OTHER_TEAM_ID = 2

function buildRow(overrides: Partial<OrganizationFeatureFlagRow> = {}): OrganizationFeatureFlagRow {
    return {
        id: 10,
        team_id: CURRENT_TEAM_ID,
        key: 'flag_key',
        name: 'Flag',
        active: true,
        filters: { groups: [] },
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        ...overrides,
    }
}

function buildSibling(teamId: number): OrganizationFeatureFlag {
    return {
        flag_id: 99,
        team_id: teamId,
        created_by: null,
        created_at: '2024-01-01T00:00:00Z',
        filters: { groups: [] },
        active: true,
    }
}

describe('cellStateFor', () => {
    const accessible = new Set([CURRENT_TEAM_ID, OTHER_TEAM_ID])

    it('does not paint a cross-project representative into the current team column before siblings load', () => {
        // Regression guard for #63155: the row's representative lives in another project, so the
        // current team's cell must wait for siblings instead of rendering the other flag's data.
        const row = buildRow({ team_id: OTHER_TEAM_ID })

        const state = cellStateFor(row, CURRENT_TEAM_ID, CURRENT_TEAM_ID, accessible, undefined, false)

        expect(state.kind).toBe('loading')
    })

    it('renders the current team cell from the representative when it belongs to the current team', () => {
        const row = buildRow({ team_id: CURRENT_TEAM_ID })

        const state = cellStateFor(row, CURRENT_TEAM_ID, CURRENT_TEAM_ID, accessible, undefined, false)

        expect(state).toEqual({ kind: 'present', sibling: expect.objectContaining({ team_id: CURRENT_TEAM_ID }) })
    })

    it('renders from the matching sibling once siblings have loaded', () => {
        const row = buildRow({ team_id: CURRENT_TEAM_ID })
        const siblings = [buildSibling(OTHER_TEAM_ID)]

        const state = cellStateFor(row, OTHER_TEAM_ID, CURRENT_TEAM_ID, accessible, siblings, false)

        expect(state).toEqual({ kind: 'present', sibling: siblings[0] })
    })

    it('marks a flag missing in a project once siblings loaded without that team', () => {
        const row = buildRow({ team_id: CURRENT_TEAM_ID })

        const state = cellStateFor(row, OTHER_TEAM_ID, CURRENT_TEAM_ID, accessible, [], false)

        expect(state.kind).toBe('missing')
    })

    it('marks a project the user cannot access as no-access', () => {
        const row = buildRow({ team_id: CURRENT_TEAM_ID })

        const state = cellStateFor(row, OTHER_TEAM_ID, CURRENT_TEAM_ID, new Set([CURRENT_TEAM_ID]), [], false)

        expect(state.kind).toBe('no-access')
    })
})
