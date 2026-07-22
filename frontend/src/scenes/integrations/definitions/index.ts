import { Integration } from '../integrationDefinition'
import { AzureDevOps } from './azureDevOps'
import { GitHub } from './github'
import { GitLab } from './gitlab'
import { Jira } from './jira'
import { Linear } from './linear'
import { Slack } from './slack'

export { Slack, GitHub, Linear, Jira, GitLab, AzureDevOps }

export const INTEGRATIONS: Integration[] = [Slack, GitHub, GitLab, AzureDevOps, Linear, Jira]

export const INTEGRATIONS_BY_SLUG: Record<string, Integration> = Object.fromEntries(
    INTEGRATIONS.map((integration) => [integration.slug, integration])
)
