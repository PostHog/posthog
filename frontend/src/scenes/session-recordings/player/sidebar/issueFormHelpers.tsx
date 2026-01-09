import { LemonDialog, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { GitHubRepositorySelectField } from 'lib/integrations/GitHubIntegrationHelpers'
import { LinearTeamSelectField } from 'lib/integrations/LinearIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

type IssueConfig = Record<string, string>

export const createLinearIssueForm = (
    sessionRecordingId: string,
    integration: IntegrationType,
    onSubmit: (integrationId: number, config: IssueConfig) => void
): void => {
    const recordingUrl = urls.absolute(urls.replay(undefined, undefined, sessionRecordingId))
    const description = `**Session Recording:** ${recordingUrl}`

    LemonDialog.openForm({
        title: 'Create Linear issue',
        shouldAwaitSubmit: true,
        initialValues: {
            title: `Issue from session replay ${sessionRecordingId.slice(0, 8)}`,
            description: description,
            integrationId: integration.id,
            teamIds: [],
        },
        content: (
            <div className="flex flex-col gap-y-2">
                <LinearTeamSelectField integrationId={integration.id} />
                <LemonField name="title" label="Title">
                    <LemonInput data-attr="issue-title" placeholder="Issue title" size="small" />
                </LemonField>
                <LemonField name="description" label="Description">
                    <LemonTextArea data-attr="issue-description" placeholder="Start typing..." />
                </LemonField>
            </div>
        ),
        errors: {
            title: (title) => (!title ? 'You must enter a title' : undefined),
            teamIds: (teamIds) => (!teamIds || teamIds.length === 0 ? 'You must choose a team' : undefined),
        },
        onSubmit: ({ title, description, teamIds }) => {
            onSubmit(integration.id, { team_id: teamIds[0], title, description })
        },
    })
}

export const createGitHubIssueForm = (
    sessionRecordingId: string,
    integration: IntegrationType,
    onSubmit: (integrationId: number, config: IssueConfig) => void
): void => {
    const recordingUrl = urls.absolute(urls.replay(undefined, undefined, sessionRecordingId))
    const body = `**Session Recording:** ${recordingUrl}`

    LemonDialog.openForm({
        title: 'Create GitHub issue',
        shouldAwaitSubmit: true,
        initialValues: {
            title: `Issue from session replay ${sessionRecordingId.slice(0, 8)}`,
            body: body,
            integrationId: integration.id,
            repositories: [],
        },
        content: (
            <div className="flex flex-col gap-y-2">
                <GitHubRepositorySelectField integrationId={integration.id} />
                <LemonField name="title" label="Title">
                    <LemonInput data-attr="issue-title" placeholder="Issue title" size="small" />
                </LemonField>
                <LemonField name="body" label="Body">
                    <LemonTextArea data-attr="issue-body" placeholder="Start typing..." />
                </LemonField>
            </div>
        ),
        errors: {
            title: (title) => (!title ? 'You must enter a title' : undefined),
            repositories: (repositories) =>
                !repositories || repositories.length === 0 ? 'You must choose a repository' : undefined,
        },
        onSubmit: ({ title, body, repositories }) => {
            onSubmit(integration.id, { repository: repositories[0], title, body })
        },
    })
}
