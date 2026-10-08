import {
    integrationsGithubAssigneesRetrieve,
    integrationsGitlabMembersRetrieve,
    integrationsJiraAssignableUsersRetrieve,
    integrationsLinearTeamMembersRetrieve,
} from 'products/integrations/frontend/generated/api'

import { IntegrationAssigneeKind, fetchIntegrationAssignees } from './integrationAssignees'

jest.mock('products/integrations/frontend/generated/api', () => ({
    integrationsGithubAssigneesRetrieve: jest.fn(),
    integrationsGitlabMembersRetrieve: jest.fn(),
    integrationsJiraAssignableUsersRetrieve: jest.fn(),
    integrationsLinearTeamMembersRetrieve: jest.fn(),
}))

const USERS = [{ id: 'u1', name: 'Ada' }]

const PROVIDER_CALLS: Record<IntegrationAssigneeKind, jest.Mock> = {
    linear: jest.mocked(integrationsLinearTeamMembersRetrieve),
    github: jest.mocked(integrationsGithubAssigneesRetrieve),
    gitlab: jest.mocked(integrationsGitlabMembersRetrieve),
    jira: jest.mocked(integrationsJiraAssignableUsersRetrieve),
}

describe('fetchIntegrationAssignees', () => {
    beforeEach(() => {
        Object.values(PROVIDER_CALLS).forEach((call) => call.mockReset().mockResolvedValue({ users: USERS }))
    })

    test.each([
        ['linear', 'team-id', { team_id: 'team-id', search: 'ad' }],
        ['github', 'posthog', { repository: 'posthog', search: 'ad' }],
        ['jira', 'ENG', { project_key: 'ENG', search: 'ad' }],
        ['gitlab', null, { search: 'ad' }],
    ] as const)('%s sends the chosen scope as its lookup parameter', async (kind, scope, params) => {
        const assignees = await fetchIntegrationAssignees('2', { integrationId: 1, kind, scope, search: 'ad' })

        expect(assignees).toEqual({ users: USERS })
        expect(PROVIDER_CALLS[kind]).toHaveBeenCalledWith('2', 1, params)
    })

    test.each(['linear', 'github', 'jira'] as const)('%s waits for a scope before calling the API', async (kind) => {
        const assignees = await fetchIntegrationAssignees('2', { integrationId: 1, kind, scope: null, search: '' })

        expect(assignees).toEqual({ users: [], reconnect_required: false })
        expect(PROVIDER_CALLS[kind]).not.toHaveBeenCalled()
    })
})
