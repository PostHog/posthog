import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { ICONS } from 'lib/integrations/utils'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { urls } from 'scenes/urls'

import { IntegrationKind, IntegrationType, SessionRecordingExternalReference } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import {
    createGitHubIssueForm,
    createGitLabIssueForm,
    createJiraIssueForm,
    createLinearIssueForm,
} from './issueFormHelpers'

const SESSION_REPLAY_INTEGRATIONS: IntegrationKind[] = ['linear', 'github', 'gitlab', 'jira']

type IssueConfig = Record<string, string>

const IntegrationIcon = ({ kind }: { kind: IntegrationKind }): JSX.Element => {
    const className = kind === 'github' ? 'w-5 h-5 rounded-sm dark:invert' : 'w-5 h-5 rounded-sm'
    return <img src={ICONS[kind]} className={className} />
}

export function PlayerSidebarLinkedIssuesTab(): JSX.Element | null {
    const { sessionRecordingId, sessionPlayerMetaData, sessionPlayerMetaDataLoading } =
        useValues(sessionRecordingPlayerLogic)
    const { createExternalReference } = useActions(sessionRecordingPlayerLogic)
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const [creatingIssue, setCreatingIssue] = useState(false)

    if (sessionPlayerMetaDataLoading || integrationsLoading) {
        return (
            <div className="p-4">
                <WrappingLoadingSkeleton fullWidth>
                    <ButtonPrimitive menuItem aria-hidden>
                        Loading
                    </ButtonPrimitive>
                </WrappingLoadingSkeleton>
            </div>
        )
    }

    const sessionReplayIntegrations = getIntegrationsByKind(SESSION_REPLAY_INTEGRATIONS)
    const externalReferences = sessionPlayerMetaData?.external_references ?? []

    const onClickCreateIssue = (integration: IntegrationType): void => {
        const submitHandler = async (integrationId: number, config: IssueConfig): Promise<void> => {
            setCreatingIssue(true)
            try {
                await createExternalReference(integrationId, config)
            } finally {
                setCreatingIssue(false)
            }
        }

        if (integration.kind === 'linear') {
            createLinearIssueForm(sessionRecordingId, integration, submitHandler)
        } else if (integration.kind === 'github') {
            createGitHubIssueForm(sessionRecordingId, integration, submitHandler)
        } else if (integration.kind === 'gitlab') {
            createGitLabIssueForm(sessionRecordingId, integration, submitHandler)
        } else if (integration.kind === 'jira') {
            createJiraIssueForm(sessionRecordingId, integration, submitHandler)
        }
    }

    const linearReferences = externalReferences.filter((ref) => ref.integration.kind === 'linear')
    const githubReferences = externalReferences.filter((ref) => ref.integration.kind === 'github')
    const gitlabReferences = externalReferences.filter((ref) => ref.integration.kind === 'gitlab')
    const jiraReferences = externalReferences.filter((ref) => ref.integration.kind === 'jira')

    const renderIssueLink = (reference: SessionRecordingExternalReference): JSX.Element => (
        <Link
            key={reference.id}
            to={reference.external_url}
            target="_blank"
            onClick={() => {
                posthog.capture('session_replay_external_issue_clicked', {
                    session_recording_id: sessionRecordingId,
                    integration_kind: reference.integration.kind,
                })
            }}
        >
            <ButtonPrimitive fullWidth>
                <div className="flex items-center gap-2 min-w-0">
                    <IntegrationIcon kind={reference.integration.kind} />
                    <span className="font-medium flex-shrink-0">{reference.issue_id}</span>
                    {reference.metadata?.repository && (
                        <span className="text-xs text-muted flex-shrink-0">[{reference.metadata.repository}]</span>
                    )}
                    {reference.metadata?.project && (
                        <span className="text-xs text-muted flex-shrink-0">[{reference.metadata.project}]</span>
                    )}
                    {reference.title && <span className="text-sm text-muted truncate">{reference.title}</span>}
                </div>
            </ButtonPrimitive>
        </Link>
    )

    return (
        <div className="p-4 space-y-4">
            <h3 className="font-semibold mb-2">Linked Issues</h3>
            {externalReferences.length > 0 ? (
                <>
                    {linearReferences.length > 0 && (
                        <div className="space-y-2">
                            <h4 className="text-sm font-medium text-muted">Linear</h4>
                            {linearReferences.map(renderIssueLink)}
                        </div>
                    )}
                    {githubReferences.length > 0 && (
                        <div className="space-y-2">
                            <h4 className="text-sm font-medium text-muted">GitHub</h4>
                            {githubReferences.map(renderIssueLink)}
                        </div>
                    )}
                    {gitlabReferences.length > 0 && (
                        <div className="space-y-2">
                            <h4 className="text-sm font-medium text-muted">GitLab</h4>
                            {gitlabReferences.map(renderIssueLink)}
                        </div>
                    )}
                    {jiraReferences.length > 0 && (
                        <div className="space-y-2">
                            <h4 className="text-sm font-medium text-muted">Jira</h4>
                            {jiraReferences.map(renderIssueLink)}
                        </div>
                    )}
                </>
            ) : (
                <p className="text-muted text-sm mb-2">No linked issues yet. Create an issue to track this session.</p>
            )}
            <CreateIssueButton
                integrations={sessionReplayIntegrations}
                onClickCreateIssue={onClickCreateIssue}
                creatingIssue={creatingIssue}
            />
        </div>
    )
}

function CreateIssueButton({
    integrations,
    onClickCreateIssue,
    creatingIssue,
}: {
    integrations: IntegrationType[]
    onClickCreateIssue: (integration: IntegrationType) => void
    creatingIssue: boolean
}): JSX.Element {
    const buttonText = creatingIssue ? 'Creating issue...' : 'Create issue'

    if (integrations.length === 0) {
        return (
            <Link
                to={urls.replaySettings('replay-integrations')}
                buttonProps={{ variant: 'panel', fullWidth: true, menuItem: true }}
                tooltip="Configure integrations"
            >
                Set up integrations
            </Link>
        )
    }

    if (integrations.length === 1) {
        return (
            <ButtonPrimitive fullWidth onClick={() => onClickCreateIssue(integrations[0])} disabled={creatingIssue}>
                <IntegrationIcon kind={integrations[0].kind} />
                {buttonText}
            </ButtonPrimitive>
        )
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive fullWidth disabled={creatingIssue}>
                    <IconPlus />
                    {buttonText}
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop matchTriggerWidth>
                <DropdownMenuGroup>
                    {integrations.map((integration) => (
                        <DropdownMenuItem key={integration.id} asChild>
                            <ButtonPrimitive menuItem onClick={() => onClickCreateIssue(integration)}>
                                <IntegrationIcon kind={integration.kind} />
                                {integration.display_name}
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
