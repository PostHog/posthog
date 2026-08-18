import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonInputSelect, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { CyclotronJobInputSchemaType } from '~/types'

import { ComposerModelEffortPickers } from 'products/posthog_ai/frontend/components/composer/ComposerModelEffortPickers'
import { modelCatalogueLogic } from 'products/posthog_ai/frontend/logics/modelCatalogueLogic'
import { ReasoningEffortEnumApi } from 'products/tasks/frontend/generated/api.schemas'

type TaskModelValue = { model?: string | null; reasoning_effort?: string | null }

/** Model and reasoning effort, from the same live gateway catalogue the AI composer uses. */
export function CyclotronJobInputTaskModel({
    value,
    onChange,
}: {
    schema: CyclotronJobInputSchemaType
    value?: TaskModelValue
    onChange: (value: TaskModelValue) => void
}): JSX.Element {
    const { catalogue, fetchedCatalogueLoading } = useValues(modelCatalogueLogic)
    const { loadCatalogue } = useActions(modelCatalogueLogic)

    useEffect(() => {
        loadCatalogue()
    }, [loadCatalogue])

    if (fetchedCatalogueLoading && !catalogue.length) {
        return <LemonSkeleton className="h-8 w-32" />
    }

    return (
        <ComposerModelEffortPickers
            models={catalogue}
            selectedModel={value?.model ?? ''}
            selectedEffort={(value?.reasoning_effort as ReasoningEffortEnumApi) ?? ReasoningEffortEnumApi.Medium}
            onModelChange={(model) => onChange({ model, reasoning_effort: null })}
            onEffortChange={(reasoning_effort) => onChange({ model: value?.model, reasoning_effort })}
        />
    )
}

type McpInstallation = { id: string; name?: string; server?: { name?: string } }

/** Shared MCP servers the run may mount. A personal installation isn't mountable by an unattended run. */
export function CyclotronJobInputTaskMcpInstallations({
    value,
    onChange,
}: {
    schema: CyclotronJobInputSchemaType
    value?: string[]
    onChange: (value: string[]) => void
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [installations, setInstallations] = useState<McpInstallation[] | null>(null)

    useEffect(() => {
        let cancelled = false
        api.get(`api/projects/${currentTeamId}/mcp_server_installations?scope=shared`)
            .then((response: { results?: McpInstallation[] }) => !cancelled && setInstallations(response.results ?? []))
            .catch(() => !cancelled && setInstallations([]))
        return () => {
            cancelled = true
        }
    }, [currentTeamId])

    if (installations === null) {
        return <LemonSkeleton className="h-8 w-full" />
    }

    return (
        <LemonInputSelect
            mode="multiple"
            value={value ?? []}
            options={installations.map((installation) => ({
                key: installation.id,
                label: installation.server?.name ?? installation.name ?? installation.id,
            }))}
            placeholder={installations.length ? 'No connectors' : 'No shared MCP servers installed'}
            disabledReason={installations.length ? undefined : 'Share an MCP server with the project first'}
            onChange={onChange}
            data-attr="task-input-mcp-installations"
        />
    )
}

export function CyclotronJobInputTaskRepository({
    value,
    onChange,
}: {
    schema: CyclotronJobInputSchemaType
    value?: string
    onChange: (value: string | null) => void
}): JSX.Element {
    const { githubIntegrations } = useValues(integrationsLogic)
    const integration = githubIntegrations?.[0]

    if (!integration) {
        return <LemonSelect value={null} options={[]} disabledReason="Connect GitHub to pick a repository" />
    }
    return <GitHubRepositoryCombobox integrationId={integration.id} value={value ?? ''} onChange={onChange} />
}
