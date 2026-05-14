import posthogComPreviewImage from 'public/deployments/posthog-com.png'

import type { DeploymentsFilters } from './fixtures'
import type { DeploymentApi, DeploymentProjectApi, PaginatedDeploymentListApi } from './generated/api.schemas'

export interface StubGitHubRepository {
    fullName: string
    name: string
    description: string
    repoUrl: string
    defaultBranch: string
    framework: string
    packageManager: string
    buildCommand: string
    outputDir: string
    nodeVersion: string
    latestCommitSha: string
    latestCommitMessage: string
    authorName: string
    authorEmail: string
}

export interface StubBuildLogLine {
    time: string
    level: 'info' | 'success' | 'warning' | 'error'
    message: string
}

export const DEMO_DEPLOYMENT_URL = 'https://posthog-com.hog.dev/'
export const POSTHOG_COM_BUILD_LOGS_URL = '/static/deployments/posthog-com-build-output-20260514T172327Z.jsonl'
export const POSTHOG_COM_PREVIEW_IMAGE_URL = posthogComPreviewImage

export const POSTHOG_COM_PROJECT_ID = '0198f4b2-2c75-7580-8ad8-b5f2cb9974a1'
export const CURRENT_DEPLOYMENT_ID = '0198f4b2-7a6e-7d7c-9f78-5b19bc11d001'

const STUB_PROJECT_ID_ALIASES: Record<string, string> = {
    'posthog--posthog-com': POSTHOG_COM_PROJECT_ID,
}

const STUB_DEPLOYMENT_ID_ALIASES: Record<string, string> = {
    'stub-deployment-posthog-com-current': CURRENT_DEPLOYMENT_ID,
    'stub-deployment-posthog-com-billing-copy': '0198f4b2-6d48-7550-b8dc-e20df74d9002',
    'stub-deployment-posthog-com-team-ben': '0198f4b2-5db4-7b4c-b913-a86dd3d4e003',
    'stub-deployment-posthog-com-hogpatch': '0198ed1a-8ad1-71e1-b63f-5cf1f8715004',
    'stub-deployment-posthog-com-logs-nav-error': '0198ecc4-3da8-7770-8e1c-a8e5ec2b5005',
    'stub-deployment-posthog-com-rn-version': '0198eb7f-2b31-71b3-8a3d-09b6748ef006',
    'stub-deployment-posthog-com-search-nav': '0198e8fb-8911-74c6-8b36-3d1a03aac007',
}

export function resolveStubProjectId(projectId: string): string {
    return STUB_PROJECT_ID_ALIASES[projectId] ?? projectId
}

export function resolveStubDeploymentId(deploymentId: string): string {
    return STUB_DEPLOYMENT_ID_ALIASES[deploymentId] ?? deploymentId
}

export function createStubUuid(): string {
    if (window.crypto?.randomUUID) {
        return window.crypto.randomUUID()
    }
    const seed = `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`.padEnd(32, '0').slice(0, 32)
    return `${seed.slice(0, 8)}-${seed.slice(8, 12)}-${seed.slice(12, 16)}-${seed.slice(16, 20)}-${seed.slice(20)}`
}

export const STUB_GITHUB_REPOSITORIES: StubGitHubRepository[] = [
    {
        fullName: 'PostHog/posthog.com',
        name: 'posthog.com',
        description: 'Official PostHog marketing site, docs, handbook, and changelog.',
        repoUrl: 'https://github.com/PostHog/posthog.com',
        defaultBranch: 'master',
        framework: 'Gatsby',
        packageManager: 'pnpm',
        buildCommand: 'pnpm build',
        outputDir: 'public',
        nodeVersion: '22.x',
        latestCommitSha: 'fe610ee60c74dec6b17972f5191dab7e025a7fec',
        latestCommitMessage: 'Remove unused error tracking snippets (#16840)',
        authorName: 'Catalin Irimie',
        authorEmail: 'catalin.i@posthog.com',
    },
]

export const INITIAL_STUB_DEPLOYMENT_PROJECTS: DeploymentProjectApi[] = [
    {
        id: POSTHOG_COM_PROJECT_ID,
        name: 'posthog.com',
        slug: 'posthog--posthog-com',
        repo_url: 'https://github.com/PostHog/posthog.com',
        default_branch: 'master',
        github_integration_id: 42,
        github_repo_id: 60554535,
        build_command: 'pnpm build',
        output_dir: 'public',
        framework: 'Gatsby',
        inject_posthog_snippet: true,
        cloudflare_project_name: 'ph-posthog--posthog-com',
        subdomain: 'posthog-com.deployments-demo.posthog.dev',
        cloudflare_ready_at: '2026-05-14T12:24:00Z',
        current_deployment: CURRENT_DEPLOYMENT_ID,
        is_ready_to_deploy: true,
        created_at: '2026-05-14T12:21:00Z',
        updated_at: '2026-05-14T12:31:00Z',
    },
]

export const INITIAL_STUB_DEPLOYMENTS_BY_PROJECT: Record<string, DeploymentApi[]> = {
    [POSTHOG_COM_PROJECT_ID]: [
        {
            id: CURRENT_DEPLOYMENT_ID,
            deployment_project_id: POSTHOG_COM_PROJECT_ID,
            status: 'ready',
            started_at: '2026-05-14T12:27:02Z',
            finished_at: '2026-05-14T12:41:52Z',
            created_at: '2026-05-14T12:26:58Z',
            commit_sha: 'fe610ee60c74dec6b17972f5191dab7e025a7fec',
            commit_message: 'Remove unused error tracking snippets (#16840)',
            commit_author_name: 'Catalin Irimie',
            commit_author_email: 'catalin.i@posthog.com',
            repo_url: 'https://github.com/PostHog/posthog.com',
            branch: 'master',
            deployment_url: DEMO_DEPLOYMENT_URL,
            preview_image_url: POSTHOG_COM_PREVIEW_IMAGE_URL,
            triggered_by_deployment: null,
            triggered_by_user_id: null,
            trigger_kind: 'git',
            error_message: '',
            error_step: '',
            cloudflare_deployment_id: 'cf-pages-posthog-com-01JVPB6JH7K0KREPV3MS2E0R0V',
            temporal_workflow_id: 'deploy-posthog-com-fe610ee60',
            is_current: true,
            duration_seconds: 890,
        },
        {
            id: '0198f4b2-6d48-7550-b8dc-e20df74d9002',
            deployment_project_id: POSTHOG_COM_PROJECT_ID,
            status: 'ready',
            started_at: '2026-05-14T12:05:11Z',
            finished_at: '2026-05-14T12:21:20Z',
            created_at: '2026-05-14T12:05:07Z',
            commit_sha: '1d2b222a9b44512f8c39a0f2c12d259ca2b90a67',
            commit_message: 'Clarify error tracking suppression billing (#16839)',
            commit_author_name: 'Catalin Irimie',
            commit_author_email: 'catalin.i@posthog.com',
            repo_url: 'https://github.com/PostHog/posthog.com',
            branch: 'master',
            deployment_url: 'https://posthog-com-git-1d2b222-posthog.deployments-demo.posthog.dev',
            preview_image_url: POSTHOG_COM_PREVIEW_IMAGE_URL,
            triggered_by_deployment: null,
            triggered_by_user_id: null,
            trigger_kind: 'git',
            error_message: '',
            error_step: '',
            cloudflare_deployment_id: 'cf-pages-posthog-com-01JVP99GJ6TYH7WQBD5EX82J7F',
            temporal_workflow_id: 'deploy-posthog-com-1d2b222a9',
            is_current: false,
            duration_seconds: 969,
        },
        {
            id: '0198f4b2-5db4-7b4c-b913-a86dd3d4e003',
            deployment_project_id: POSTHOG_COM_PROJECT_ID,
            status: 'ready',
            started_at: '2026-05-14T11:42:40Z',
            finished_at: '2026-05-14T11:57:25Z',
            created_at: '2026-05-14T11:42:36Z',
            commit_sha: '27f19a53a54d742f9919ecbb78656eefb83763a8',
            commit_message: 'add secret /teams/team-ben page (#16833)',
            commit_author_name: 'Ben White',
            commit_author_email: 'ben@posthog.com',
            repo_url: 'https://github.com/PostHog/posthog.com',
            branch: 'master',
            deployment_url: 'https://posthog-com-git-27f19a5-posthog.deployments-demo.posthog.dev',
            preview_image_url: POSTHOG_COM_PREVIEW_IMAGE_URL,
            triggered_by_deployment: null,
            triggered_by_user_id: null,
            trigger_kind: 'git',
            error_message: '',
            error_step: '',
            cloudflare_deployment_id: 'cf-pages-posthog-com-01JVP8V8D8XX4QW5NA7C6G9FBX',
            temporal_workflow_id: 'deploy-posthog-com-27f19a53a',
            is_current: false,
            duration_seconds: 885,
        },
        {
            id: '0198ed1a-8ad1-71e1-b63f-5cf1f8715004',
            deployment_project_id: POSTHOG_COM_PROJECT_ID,
            status: 'ready',
            started_at: '2026-05-13T18:04:17Z',
            finished_at: '2026-05-13T18:18:01Z',
            created_at: '2026-05-13T18:04:12Z',
            commit_sha: 'c9c813b02add9fd5b55d85d30ac2f9593b977d97',
            commit_message: 'Updates to Hogpatch ops pages (#16648)',
            commit_author_name: 'Scott Lewis',
            commit_author_email: 'scott.l@posthog.com',
            repo_url: 'https://github.com/PostHog/posthog.com',
            branch: 'master',
            deployment_url: 'https://posthog-com-git-c9c813b-posthog.deployments-demo.posthog.dev',
            preview_image_url: POSTHOG_COM_PREVIEW_IMAGE_URL,
            triggered_by_deployment: null,
            triggered_by_user_id: null,
            trigger_kind: 'git',
            error_message: '',
            error_step: '',
            cloudflare_deployment_id: 'cf-pages-posthog-com-01JVMYF8X3B2SX7V9FTJQ6C0Y1',
            temporal_workflow_id: 'deploy-posthog-com-c9c813b02',
            is_current: false,
            duration_seconds: 824,
        },
        {
            id: '0198ecc4-3da8-7770-8e1c-a8e5ec2b5005',
            deployment_project_id: POSTHOG_COM_PROJECT_ID,
            status: 'error',
            started_at: '2026-05-13T15:12:21Z',
            finished_at: '2026-05-13T15:13:36Z',
            created_at: '2026-05-13T15:12:17Z',
            commit_sha: 'fbe4c5543d4e4b7da201d26c5a0c6a928d528744',
            commit_message: "docs(logs): add 'Set up alerts' entry to navigation menu (#16831)",
            commit_author_name: 'Jon McCallum',
            commit_author_email: '66999846+jonmcwest@users.noreply.github.com',
            repo_url: 'https://github.com/PostHog/posthog.com',
            branch: 'docs/logs-alerts-nav',
            deployment_url: '',
            preview_image_url: '',
            triggered_by_deployment: null,
            triggered_by_user_id: null,
            trigger_kind: 'git',
            error_message: 'gatsby build failed while validating docs navigation: duplicate slug /docs/logs/alerts.',
            error_step: 'build',
            cloudflare_deployment_id: '',
            temporal_workflow_id: 'deploy-posthog-com-fbe4c5543',
            is_current: false,
            duration_seconds: 75,
        },
        {
            id: '0198eb7f-2b31-71b3-8a3d-09b6748ef006',
            deployment_project_id: POSTHOG_COM_PROJECT_ID,
            status: 'ready',
            started_at: '2026-05-13T09:18:55Z',
            finished_at: '2026-05-13T09:33:37Z',
            created_at: '2026-05-13T09:18:50Z',
            commit_sha: 'b0608d06390245ff61a8ad3cdcce94e7fedeee8d',
            commit_message: 'docs: correct React Native version for evaluation_contexts (#16830)',
            commit_author_name: 'posthog[bot]',
            commit_author_email: '206114724+posthog[bot]@users.noreply.github.com',
            repo_url: 'https://github.com/PostHog/posthog.com',
            branch: 'master',
            deployment_url: 'https://posthog-com-git-b0608d0-posthog.deployments-demo.posthog.dev',
            preview_image_url: POSTHOG_COM_PREVIEW_IMAGE_URL,
            triggered_by_deployment: null,
            triggered_by_user_id: null,
            trigger_kind: 'git',
            error_message: '',
            error_step: '',
            cloudflare_deployment_id: 'cf-pages-posthog-com-01JVKQYPDGCHSATG5CJ6MHM4JS',
            temporal_workflow_id: 'deploy-posthog-com-b0608d063',
            is_current: false,
            duration_seconds: 882,
        },
        {
            id: '0198e8fb-8911-74c6-8b36-3d1a03aac007',
            deployment_project_id: POSTHOG_COM_PROJECT_ID,
            status: 'ready',
            started_at: '2026-05-12T21:54:09Z',
            finished_at: '2026-05-12T22:08:44Z',
            created_at: '2026-05-12T21:54:04Z',
            commit_sha: '560aeccc8643b669fb632a9cddfc1a7a2afb454b',
            commit_message: 'defer search navigation (#16829)',
            commit_author_name: 'Eli Kinsey',
            commit_author_email: 'eli@ekinsey.dev',
            repo_url: 'https://github.com/PostHog/posthog.com',
            branch: 'master',
            deployment_url: 'https://posthog-com-git-560aecc-posthog.deployments-demo.posthog.dev',
            preview_image_url: POSTHOG_COM_PREVIEW_IMAGE_URL,
            triggered_by_deployment: null,
            triggered_by_user_id: null,
            trigger_kind: 'git',
            error_message: '',
            error_step: '',
            cloudflare_deployment_id: 'cf-pages-posthog-com-01JVHY9DRH7JJPCY2PNF8HRP6N',
            temporal_workflow_id: 'deploy-posthog-com-560aeccc',
            is_current: false,
            duration_seconds: 875,
        },
    ],
}

export function cloneInitialStubProjects(): DeploymentProjectApi[] {
    return INITIAL_STUB_DEPLOYMENT_PROJECTS.map((project) => ({ ...project }))
}

export function cloneInitialStubDeploymentsByProject(): Record<string, DeploymentApi[]> {
    return Object.fromEntries(
        Object.entries(INITIAL_STUB_DEPLOYMENTS_BY_PROJECT).map(([projectId, deployments]) => [
            projectId,
            deployments.map((deployment) => ({ ...deployment })),
        ])
    )
}

export function getInitialStubProject(projectId: string): DeploymentProjectApi | null {
    const resolvedProjectId = resolveStubProjectId(projectId)
    const project = INITIAL_STUB_DEPLOYMENT_PROJECTS.find(
        (stubProject) => stubProject.id === resolvedProjectId || stubProject.slug === projectId
    )
    return project ? { ...project } : null
}

export function getInitialStubDeployment(projectId: string, deploymentId: string): DeploymentApi | null {
    const resolvedProjectId = resolveStubProjectId(projectId)
    const resolvedDeploymentId = resolveStubDeploymentId(deploymentId)
    const deployment = INITIAL_STUB_DEPLOYMENTS_BY_PROJECT[resolvedProjectId]?.find(
        (stubDeployment) => stubDeployment.id === resolvedDeploymentId
    )
    return deployment ? { ...deployment } : null
}

export function getStubRepository(fullName: string): StubGitHubRepository | null {
    return STUB_GITHUB_REPOSITORIES.find((repository) => repository.fullName === fullName) ?? null
}

export function createStubProject(
    repository: StubGitHubRepository,
    projectId: string,
    now: string
): DeploymentProjectApi {
    const slug =
        repository.fullName
            .split('/')
            .pop()
            ?.replace(/[^a-zA-Z0-9_-]/g, '-')
            .toLowerCase() || projectId

    return {
        id: projectId,
        name: repository.name,
        slug,
        repo_url: repository.repoUrl,
        default_branch: repository.defaultBranch,
        github_integration_id: 42,
        github_repo_id: Math.abs(hashString(repository.fullName)),
        build_command: repository.buildCommand,
        output_dir: repository.outputDir,
        framework: repository.framework,
        inject_posthog_snippet: true,
        cloudflare_project_name: `ph-${slug}`,
        subdomain: `${slug}.deployments-demo.posthog.dev`,
        cloudflare_ready_at: now,
        current_deployment: null,
        is_ready_to_deploy: true,
        created_at: now,
        updated_at: now,
    }
}

export function createStubDeployment({
    id,
    projectId,
    repository,
    now,
    triggerKind,
    triggeredByDeploymentId,
    status = 'building',
}: {
    id: string
    projectId: string
    repository: StubGitHubRepository
    now: string
    triggerKind: DeploymentApi['trigger_kind']
    triggeredByDeploymentId?: string | null
    status?: DeploymentApi['status']
}): DeploymentApi {
    const isReady = status === 'ready'
    return {
        id,
        deployment_project_id: projectId,
        status,
        started_at: now,
        finished_at: isReady ? addSeconds(now, 890) : null,
        created_at: now,
        commit_sha: repository.latestCommitSha,
        commit_message: repository.latestCommitMessage,
        commit_author_name: repository.authorName,
        commit_author_email: repository.authorEmail,
        repo_url: repository.repoUrl,
        branch: repository.defaultBranch,
        deployment_url: isReady ? DEMO_DEPLOYMENT_URL : '',
        preview_image_url: isReady ? POSTHOG_COM_PREVIEW_IMAGE_URL : '',
        triggered_by_deployment: triggeredByDeploymentId ?? null,
        triggered_by_user_id: null,
        trigger_kind: triggerKind,
        error_message: '',
        error_step: '',
        cloudflare_deployment_id: isReady ? `cf-pages-${id}` : '',
        temporal_workflow_id: `deploy-posthog-com-${repository.latestCommitSha.slice(0, 9)}`,
        is_current: isReady,
        duration_seconds: isReady ? 890 : 0,
    }
}

export function createStubRedeployment({
    id,
    source,
    now,
}: {
    id: string
    source: DeploymentApi
    now: string
}): DeploymentApi {
    return {
        ...source,
        id,
        status: 'building',
        started_at: now,
        finished_at: null,
        created_at: now,
        deployment_url: '',
        preview_image_url: '',
        triggered_by_deployment: source.id,
        triggered_by_user_id: null,
        trigger_kind: 'redeploy',
        error_message: '',
        error_step: '',
        cloudflare_deployment_id: '',
        temporal_workflow_id: `deploy-posthog-com-${source.commit_sha?.slice(0, 9) || id}`,
        is_current: false,
        duration_seconds: 0,
    }
}

export function createStubRollbackDeployment({
    id,
    target,
    now,
}: {
    id: string
    target: DeploymentApi
    now: string
}): DeploymentApi {
    return {
        ...target,
        id,
        status: 'ready',
        started_at: now,
        finished_at: addSeconds(now, 12),
        created_at: now,
        deployment_url: DEMO_DEPLOYMENT_URL,
        preview_image_url: POSTHOG_COM_PREVIEW_IMAGE_URL,
        triggered_by_deployment: target.id,
        triggered_by_user_id: null,
        trigger_kind: 'rollback',
        error_message: '',
        error_step: '',
        cloudflare_deployment_id: `cf-pages-${id}`,
        temporal_workflow_id: `deploy-posthog-com-rollback-${target.commit_sha?.slice(0, 7) || id}`,
        is_current: true,
        duration_seconds: 12,
    }
}

export function makeStubDeploymentReady(
    deployment: DeploymentApi,
    project: DeploymentProjectApi,
    finishedAt: string = addSeconds(deployment.started_at ?? deployment.created_at, 890)
): DeploymentApi {
    const startedAt = deployment.started_at ?? deployment.created_at
    const durationSeconds = Math.max(
        1,
        Math.round((new Date(finishedAt).getTime() - new Date(startedAt).getTime()) / 1000)
    )

    return {
        ...deployment,
        status: 'ready',
        finished_at: finishedAt,
        deployment_url: project.subdomain ? `https://${project.subdomain}` : DEMO_DEPLOYMENT_URL,
        preview_image_url: POSTHOG_COM_PREVIEW_IMAGE_URL,
        cloudflare_deployment_id: deployment.cloudflare_deployment_id || `cf-pages-${deployment.id}`,
        is_current: true,
        duration_seconds: durationSeconds,
    }
}

export function getStubDeploymentsResponse(
    deployments: DeploymentApi[],
    filters: DeploymentsFilters,
    pageSize: number
): PaginatedDeploymentListApi {
    let rows = [...deployments]

    const search = filters.search.trim().toLowerCase()
    if (search) {
        rows = rows.filter((deployment) =>
            [
                deployment.id,
                deployment.commit_sha,
                deployment.commit_message,
                deployment.commit_author_name,
                deployment.commit_author_email,
                deployment.branch,
                deployment.repo_url,
            ]
                .filter(Boolean)
                .some((value) => String(value).toLowerCase().includes(search))
        )
    }

    if (filters.status.length > 0) {
        rows = rows.filter((deployment) => filters.status.includes(deployment.status))
    }

    if (filters.author) {
        rows = rows.filter((deployment) => deployment.commit_author_email === filters.author)
    }

    rows.sort((a, b) => compareDeployments(a, b, filters.order))

    const offset = (filters.page - 1) * pageSize
    return {
        count: rows.length,
        next: offset + pageSize < rows.length ? 'stub-next-page' : null,
        previous: offset > 0 ? 'stub-previous-page' : null,
        results: rows.slice(offset, offset + pageSize),
    }
}

export function getStubBuildLogs(deployment: DeploymentApi, project: DeploymentProjectApi | null): StubBuildLogLine[] {
    const framework = project?.framework || 'Gatsby'
    const buildCommand = project?.build_command || 'pnpm build'
    const outputDir = project?.output_dir || 'public'
    const packageManager = buildCommand.startsWith('pnpm') ? 'pnpm' : buildCommand.startsWith('yarn') ? 'yarn' : 'npm'

    const baseLines: StubBuildLogLine[] = [
        {
            time: '00:00',
            level: 'info',
            message: `Queued deployment ${deployment.id}`,
        },
        {
            time: '00:04',
            level: 'info',
            message: `Cloning ${deployment.repo_url} (${deployment.branch})`,
        },
        {
            time: '00:09',
            level: 'success',
            message: `Checked out ${deployment.commit_sha?.slice(0, 9)}`,
        },
        {
            time: '00:12',
            level: 'info',
            message: 'Using Node.js 22.x and pnpm 10 from repository configuration',
        },
        {
            time: '00:17',
            level: 'info',
            message: `Detected ${framework}; output directory is ${outputDir}`,
        },
        {
            time: '00:23',
            level: 'info',
            message: `Installing dependencies with ${packageManager}`,
        },
        {
            time: '00:39',
            level: 'success',
            message: 'Restored Gatsby cache and pnpm store',
        },
        { time: '00:46', level: 'info', message: `Running ${buildCommand}` },
        {
            time: '01:58',
            level: 'info',
            message: 'success compile gatsby files - 1m 12s',
        },
        {
            time: '05:34',
            level: 'info',
            message: 'success Building production JavaScript and CSS bundles - 3m 36s',
        },
    ]

    if (deployment.status === 'queued' || deployment.status === 'initializing') {
        return baseLines.slice(0, 4)
    }

    if (deployment.status === 'building') {
        return [
            ...baseLines,
            {
                time: '07:12',
                level: 'info',
                message: 'success Building HTML renderer - 1m 38s',
            },
            {
                time: '08:01',
                level: 'info',
                message: 'Generating static pages (0/4208)…',
            },
            {
                time: '10:44',
                level: 'info',
                message: 'Generating static pages (2840/4208)…',
            },
            {
                time: '12:03',
                level: 'info',
                message: 'Uploading build artifacts…',
            },
        ]
    }

    if (deployment.status === 'error') {
        return [
            ...baseLines,
            {
                time: '01:03',
                level: 'error',
                message: deployment.error_message || 'Build failed with an unknown error.',
            },
            {
                time: '01:15',
                level: 'error',
                message: 'Deployment failed before publishing.',
            },
        ]
    }

    if (deployment.status === 'cancelled') {
        return [
            ...baseLines,
            {
                time: '01:15',
                level: 'warning',
                message: 'Deployment cancelled by user.',
            },
        ]
    }

    return [
        ...baseLines,
        {
            time: '07:12',
            level: 'success',
            message: 'success Building HTML renderer - 1m 38s',
        },
        {
            time: '10:46',
            level: 'info',
            message: 'Generating static pages (4208/4208)',
        },
        {
            time: '11:47',
            level: 'success',
            message: 'success Building static HTML for pages - 3m 46s',
        },
        {
            time: '12:14',
            level: 'info',
            message: 'Checking redirects and generated sitemap',
        },
        { time: '12:42', level: 'info', message: 'Uploading build artifacts…' },
        {
            time: '14:38',
            level: 'success',
            message: 'Published to edge network',
        },
        {
            time: '14:50',
            level: 'success',
            message: `Production URL: ${deployment.deployment_url || DEMO_DEPLOYMENT_URL}`,
        },
    ]
}

function compareDeployments(a: DeploymentApi, b: DeploymentApi, order: string): number {
    const descending = order.startsWith('-')
    const field = descending ? order.slice(1) : order
    const value = (deployment: DeploymentApi): number | string => {
        if (field === 'started_at' || field === 'finished_at' || field === 'created_at') {
            return new Date(deployment[field] || 0).getTime()
        }
        return String(deployment[field as keyof DeploymentApi] ?? '')
    }
    const left = value(a)
    const right = value(b)
    const result = left > right ? 1 : left < right ? -1 : 0
    return descending ? -result : result
}

function addSeconds(iso: string, seconds: number): string {
    return new Date(new Date(iso).getTime() + seconds * 1000).toISOString()
}

function hashString(value: string): number {
    return value.split('').reduce((hash, character) => (hash * 31 + character.charCodeAt(0)) | 0, 0)
}
