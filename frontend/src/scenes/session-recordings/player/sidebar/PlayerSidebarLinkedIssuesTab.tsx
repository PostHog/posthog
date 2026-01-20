import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonDialog, LemonInput, LemonTextArea, Link } from '@posthog/lemon-ui'

import { LinearTeamSelectField } from 'lib/integrations/LinearIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { ICONS } from 'lib/integrations/utils'
import { LemonField } from 'lib/lemon-ui/LemonField'
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

import { IntegrationKind, IntegrationType } from '~/types'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

const SESSION_REPLAY_INTEGRATIONS: IntegrationKind[] = ['linear']

type IssueConfig = Record<string, string>

const IntegrationIcon = ({ kind }: { kind: IntegrationKind }): JSX.Element => {
    return <img src={ICONS[kind]} className="w-5 h-5 rounded-sm" />
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
        if (integration.kind === 'linear') {
            createLinearIssueForm(
                sessionRecordingId,
                integration,
                async (integrationId: number, config: IssueConfig) => {
                    setCreatingIssue(true)
                    try {
                        await createExternalReference(integrationId, config)
                    } finally {
                        setCreatingIssue(false)
                    }
                }
            )
        }
    }

    return (
        <div className="p-4 space-y-2">
            <h3 className="font-semibold mb-2">Linked Issues</h3>
            {externalReferences.length > 0 ? (
                externalReferences.map((reference) => (
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
                                {reference.title && (
                                    <span className="text-sm text-muted truncate">{reference.title}</span>
                                )}
                            </div>
                        </ButtonPrimitive>
                    </Link>
                ))
            ) : (
                <p className="text-muted text-sm mb-2">
                    No linked issues yet. Create an issue in Linear to track this session.
                </p>
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
                tooltip="Configure Linear integration"
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

const createLinearIssueForm = (
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
