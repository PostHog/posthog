import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { deploymentsLogic } from '../deploymentsLogic'
import {
    createStubDeployment,
    createStubProject,
    createStubUuid,
    getSeedDataForRepo,
    getStubRepository,
} from '../stubData'
import type { stubAddProjectLogicType } from './stubAddProjectLogicType'

const slugify = (value: string): string =>
    value
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 80)

export const stubAddProjectLogic = kea<stubAddProjectLogicType>([
    path(['products', 'deployments', 'frontend', 'components', 'stubAddProjectLogic']),
    connect(() => ({
        values: [deploymentsLogic, ['deploymentProjects']],
        actions: [deploymentsLogic, ['addStubProject', 'closeAddProjectModal']],
    })),
    actions({
        setRepoName: (repoName: string) => ({ repoName }),
        setName: (name: string) => ({ name }),
        setSlug: (slug: string) => ({ slug }),
        setSubmitting: (submitting: boolean) => ({ submitting }),
        setError: (error: string | null) => ({ error }),
        reset: true,
        submit: true,
    }),
    reducers({
        repoName: [
            '',
            {
                setRepoName: (_, { repoName }) => repoName,
                reset: () => '',
            },
        ],
        name: [
            '',
            {
                setName: (_, { name }) => name,
                setRepoName: (_, { repoName }) => repoName.split('/').pop() ?? repoName,
                reset: () => '',
            },
        ],
        slug: [
            '',
            {
                setSlug: (_, { slug }) => slug,
                setName: (_, { name }) => slugify(name),
                setRepoName: (_, { repoName }) => slugify(repoName.split('/').pop() ?? repoName),
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
                setRepoName: () => null,
                setName: () => null,
                setSlug: () => null,
                reset: () => null,
            },
        ],
    }),
    selectors({
        canSubmit: [
            (s) => [s.repoName, s.name, s.slug, s.submitting],
            (repoName, name, slug, submitting): boolean => !!repoName && !!name.trim() && !!slug.trim() && !submitting,
        ],
    }),
    listeners(({ actions, values }) => ({
        submit: () => {
            const repository = getStubRepository(values.repoName)
            const name = values.name.trim()
            const slug = values.slug.trim()
            if (!repository || !name || !slug) {
                actions.setError('Choose a repository and project name.')
                return
            }
            if (values.deploymentProjects.some((project) => project.slug === slug)) {
                actions.setError('A deployment project with this slug already exists.')
                return
            }

            actions.setSubmitting(true)
            actions.setError(null)

            // For repos we have rich pre-baked data for, hydrate the project
            // with its full deployment history at once. Other repos get the
            // synthetic single-build path.
            const seed = getSeedDataForRepo(values.repoName)
            if (seed) {
                actions.addStubProject(seed.project, seed.deployments)
                actions.closeAddProjectModal()
                actions.reset()
                lemonToast.success('Project connected.')
                router.actions.push(urls.deploymentProject(seed.project.id))
                return
            }

            const now = new Date().toISOString()
            const projectId = createStubUuid()
            const project = {
                ...createStubProject(repository, projectId, now),
                name,
                slug,
                cloudflare_project_name: `ph-${slug}`,
                subdomain: `${slug}.deployments-demo.posthog.dev`,
            }
            const deployment = createStubDeployment({
                id: createStubUuid(),
                projectId,
                repository,
                now,
                triggerKind: 'manual',
            })

            actions.addStubProject(project, [deployment])
            actions.closeAddProjectModal()
            actions.reset()
            lemonToast.success('Project connected. First deployment started.')
            router.actions.push(urls.deploymentProject(project.id))
        },
    })),
])
