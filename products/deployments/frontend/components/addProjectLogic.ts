import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { githubIntegrationLogic } from 'lib/integrations/githubIntegrationLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import { deploymentsLogic } from '../deploymentsLogic'
import { deploymentProjectsCreate, deploymentProjectsDeploymentsCreate } from '../generated/api'
import type { addProjectLogicType } from './addProjectLogicType'

const slugify = (s: string): string =>
    s
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 80)

export const addProjectLogic = kea<addProjectLogicType>([
    path(['products', 'deployments', 'frontend', 'components', 'addProjectLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], integrationsLogic, ['integrations']],
        actions: [deploymentsLogic, ['loadDeploymentProjects', 'closeAddProjectModal']],
    })),
    actions({
        setIntegrationId: (integrationId: number | null) => ({ integrationId }),
        setRepoName: (repoName: string) => ({ repoName }),
        setName: (name: string) => ({ name }),
        setSlug: (slug: string) => ({ slug }),
        setSubmitting: (submitting: boolean) => ({ submitting }),
        setError: (error: string | null) => ({ error }),
        reset: true,
        submit: true,
    }),
    reducers({
        integrationId: [
            null as number | null,
            {
                setIntegrationId: (_, { integrationId }) => integrationId,
                reset: () => null,
            },
        ],
        repoName: [
            '',
            {
                setRepoName: (_, { repoName }) => repoName,
                // Switching integrations invalidates the previously picked repo.
                setIntegrationId: () => '',
                reset: () => '',
            },
        ],
        name: [
            '',
            {
                setName: (_, { name }) => name,
                setRepoName: (_, { repoName }) => {
                    // Autofill the project name from the repo's short name on first pick.
                    const base = repoName.includes('/') ? (repoName.split('/').pop() ?? '') : repoName
                    return base
                },
                setIntegrationId: () => '',
                reset: () => '',
            },
        ],
        slug: [
            '',
            {
                setSlug: (_, { slug }) => slug,
                setName: (_, { name }) => slugify(name),
                setRepoName: (_, { repoName }) => {
                    const base = repoName.includes('/') ? (repoName.split('/').pop() ?? '') : repoName
                    return slugify(base)
                },
                setIntegrationId: () => '',
                reset: () => '',
            },
        ],
        submitting: [
            false,
            {
                setSubmitting: (_, { submitting }) => submitting,
                reset: () => false,
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_, { error }) => error,
                setIntegrationId: () => null,
                setRepoName: () => null,
                setName: () => null,
                setSlug: () => null,
                reset: () => null,
            },
        ],
    }),
    selectors({
        githubIntegrations: [
            (s) => [s.integrations],
            (integrations: IntegrationType[] | null): IntegrationType[] =>
                (integrations ?? []).filter((i) => i.kind === 'github'),
        ],
        canSubmit: [
            (s) => [s.integrationId, s.repoName, s.name, s.slug, s.submitting],
            (integrationId, repoName, name, slug, submitting): boolean =>
                !!integrationId && !!repoName && !!name.trim() && !!slug.trim() && !submitting,
        ],
    }),
    listeners(({ actions, values }) => ({
        submit: async () => {
            const teamId = values.currentTeamId
            const integrationId = values.integrationId
            const repoName = values.repoName
            if (!teamId || !integrationId || !repoName) {
                return
            }
            // Resolve repo id from the integration's repository list.
            const githubLogic = githubIntegrationLogic({ id: integrationId })
            const repo = githubLogic.values.repositories.find((r) => r.name === repoName)
            if (!repo) {
                actions.setError('Could not resolve repository — try reselecting it.')
                return
            }

            actions.setSubmitting(true)
            actions.setError(null)
            try {
                const created = await deploymentProjectsCreate(String(teamId), {
                    name: values.name.trim(),
                    slug: values.slug.trim(),
                    github_integration_id: integrationId,
                    github_repo_id: repo.id,
                })
                // Auto-deploy on create — user-confirmed behavior.
                try {
                    await deploymentProjectsDeploymentsCreate(String(teamId), created.id, {})
                } catch (e: any) {
                    // Project exists but initial deployment failed; surface a
                    // toast and still close the modal so the user can retry
                    // from the project's page.
                    lemonToast.warning(
                        `Project created, but initial deployment couldn't start: ${e?.message ?? 'unknown error'}`
                    )
                }
                actions.loadDeploymentProjects()
                actions.closeAddProjectModal()
                actions.reset()
                router.actions.push(urls.deploymentProject(created.id))
            } catch (e: any) {
                actions.setError(e?.message ?? 'Failed to create project')
            } finally {
                actions.setSubmitting(false)
            }
        },
    })),
])
