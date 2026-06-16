import { Integration } from '../integrationDefinition'
import { GitHub } from './github'
import { GitLab } from './gitlab'
import { Jira } from './jira'
import { Linear } from './linear'
import { Slack } from './slack'

export { Slack, GitHub, Linear, Jira, GitLab }

export const INTEGRATIONS: Integration[] = [Slack, GitHub, Linear, Jira, GitLab]

export const INTEGRATIONS_BY_SLUG: Record<string, Integration> = Object.fromEntries(
    INTEGRATIONS.map((integration) => [integration.slug, integration])
)
