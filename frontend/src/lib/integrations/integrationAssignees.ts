import {
    integrationsGithubAssigneesRetrieve,
    integrationsGitlabMembersRetrieve,
    integrationsJiraAssignableUsersRetrieve,
    integrationsLinearTeamMembersRetrieve,
} from 'products/integrations/frontend/generated/api'
import type {
    IntegrationAssigneeApi,
    IntegrationAssigneesResponseApi,
} from 'products/integrations/frontend/generated/api.schemas'

export type IntegrationAssigneeKind = 'linear' | 'github' | 'gitlab' | 'jira'
export type IntegrationAssignee = IntegrationAssigneeApi
// An interface, not an alias, so kea-typegen keeps this name instead of importing the generated type into callers.
export interface IntegrationAssignees extends IntegrationAssigneesResponseApi {}

export interface IntegrationAssigneesQuery {
    integrationId: number
    kind: IntegrationAssigneeKind
    /** The Linear team, GitHub repository, or Jira project the issue is created in. GitLab needs none. */
    scope: string | null
    search: string
}

const NO_INTEGRATION_ASSIGNEES: IntegrationAssignees = { users: [], reconnect_required: false }

/** Lists the users an external issue can be assigned to. Returns no users until a required scope is chosen. */
export async function fetchIntegrationAssignees(
    projectId: string,
    { integrationId, kind, scope, search }: IntegrationAssigneesQuery
): Promise<IntegrationAssignees> {
    switch (kind) {
        case 'gitlab':
            return await integrationsGitlabMembersRetrieve(projectId, integrationId, { search })
        case 'linear':
            return scope
                ? await integrationsLinearTeamMembersRetrieve(projectId, integrationId, { team_id: scope, search })
                : NO_INTEGRATION_ASSIGNEES
        case 'github':
            return scope
                ? await integrationsGithubAssigneesRetrieve(projectId, integrationId, { repository: scope, search })
                : NO_INTEGRATION_ASSIGNEES
        case 'jira':
            return scope
                ? await integrationsJiraAssignableUsersRetrieve(projectId, integrationId, {
                      project_key: scope,
                      search,
                  })
                : NO_INTEGRATION_ASSIGNEES
    }
}
