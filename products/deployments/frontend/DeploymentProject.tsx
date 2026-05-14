import { BindLogic, useActions, useValues } from 'kea'

import { IconExternal, IconGithub } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    PaginationManual,
} from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CurrentDeploymentCard } from './components/CurrentDeploymentCard'
import { DeploymentsFilters } from './components/DeploymentsFilters'
import { DeploymentStatusTag } from './components/DeploymentStatusTag'
import { deploymentProjectLogic, DeploymentProjectLogicProps } from './deploymentProjectLogic'
import { deploymentsLogic } from './deploymentsLogic'
import { Deployment, DEPLOYMENTS_PER_PAGE, DeploymentStatus, formatDuration } from './fixtures'

export const scene: SceneExport<DeploymentProjectLogicProps> = {
    component: DeploymentProject,
    logic: deploymentProjectLogic,
    paramsToProps: ({ params: { projectId } }) => ({ projectId }),
}

export function DeploymentProject({ projectId }: DeploymentProjectLogicProps): JSX.Element {
    return (
        <BindLogic logic={deploymentProjectLogic} props={{ projectId }}>
            <DeploymentProjectInner projectId={projectId} />
        </BindLogic>
    )
}

function DeploymentProjectInner({ projectId }: DeploymentProjectLogicProps): JSX.Element {
    const {
        deploymentProject,
        deployments,
        deploymentsCount,
        deploymentsLoading,
        currentDeployment,
        filters,
        shouldShowEmptyState,
    } = useValues(deploymentProjectLogic({ projectId }))
    const { setFilters, redeployDeployment, rollbackDeployment } = useActions(deploymentProjectLogic({ projectId }))
    const { deploymentProjectsLoading } = useValues(deploymentsLogic)

    if (!deploymentProject && !deploymentProjectsLoading) {
        return (
            <SceneContent>
                <NotFound object="deployment project" />
            </SceneContent>
        )
    }

    const confirmRedeploy = (d: Deployment): void => {
        LemonDialog.open({
            title: 'Redeploy?',
            description: `This will start a new deployment based on ${d.commit_sha || d.id}. It will run through the build pipeline before becoming current.`,
            primaryButton: {
                children: 'Redeploy',
                type: 'primary',
                onClick: () => redeployDeployment(d.id),
            },
            secondaryButton: { children: 'Cancel', type: 'secondary' },
        })
    }

    const confirmRollback = (d: Deployment): void => {
        LemonDialog.open({
            title: 'Roll back to this deployment?',
            description: `This will immediately make ${d.commit_message || d.id} current.`,
            primaryButton: {
                children: 'Roll back',
                type: 'primary',
                status: 'danger',
                onClick: () => rollbackDeployment(d.id),
            },
            secondaryButton: { children: 'Cancel', type: 'secondary' },
        })
    }

    const columns: LemonTableColumns<Deployment> = [
        {
            title: 'Deployment',
            dataIndex: 'id',
            sticky: true,
            render: (_, d) => (
                <LemonTableLink
                    to={urls.deployment(projectId, d.id)}
                    title={
                        <span className="flex items-center gap-2 min-w-0">
                            <span className="truncate">{d.commit_message || d.id}</span>
                            {d.is_current && <LemonTag type="success">Current</LemonTag>}
                        </span>
                    }
                />
            ),
        },
        {
            title: 'Status',
            dataIndex: 'status',
            sorter: (a, b) => a.status.localeCompare(b.status),
            render: (status) => <DeploymentStatusTag status={status as DeploymentStatus} />,
        },
        {
            title: 'Duration',
            dataIndex: 'duration_seconds',
            sorter: (a, b) => (a.duration_seconds ?? -1) - (b.duration_seconds ?? -1),
            render: (_, d) => formatDuration(d.duration_seconds),
        },
        createdAtColumn<Deployment>() as LemonTableColumns<Deployment>[number],
        {
            title: 'Author',
            dataIndex: 'commit_author_name',
            sorter: (a, b) => (a.commit_author_name ?? '').localeCompare(b.commit_author_name ?? ''),
            render: (_, d) => (
                <ProfilePicture
                    user={{
                        first_name: d.commit_author_name ?? '',
                        email: d.commit_author_email ?? '',
                    }}
                    size="sm"
                    showName
                />
            ),
        },
        {
            width: 0,
            render: (_, d) => (
                <More
                    overlay={
                        <>
                            <LemonButton fullWidth onClick={() => confirmRedeploy(d)}>
                                Redeploy
                            </LemonButton>
                            <LemonButton
                                fullWidth
                                onClick={() => confirmRollback(d)}
                                disabledReason={d.is_current ? 'Already current' : undefined}
                            >
                                Rollback
                            </LemonButton>
                            {d.repo_url && d.commit_sha && (
                                <LemonButton fullWidth to={`${d.repo_url}/commit/${d.commit_sha}`} targetBlank>
                                    View source
                                </LemonButton>
                            )}
                            <LemonButton
                                fullWidth
                                to={d.deployment_url || undefined}
                                targetBlank
                                disabledReason={!d.deployment_url ? 'Not available' : undefined}
                            >
                                View live
                            </LemonButton>
                        </>
                    }
                />
            ),
        },
    ]

    const pagination: PaginationManual = {
        controlled: true,
        pageSize: DEPLOYMENTS_PER_PAGE,
        currentPage: filters.page,
        entryCount: deploymentsCount,
        onForward: () => setFilters({ page: filters.page + 1 }),
        onBackward: () => setFilters({ page: Math.max(1, filters.page - 1) }),
    }

    const repoLabel = deploymentProject?.repo_url?.replace('https://github.com/', '')
    const liveUrl = deploymentProject?.subdomain ? `https://${deploymentProject.subdomain}` : null

    return (
        <SceneContent>
            <SceneTitleSection
                name={deploymentProject?.name ?? 'Deployment project'}
                description={
                    deploymentProject
                        ? `${repoLabel ?? ''}${deploymentProject.default_branch ? ` · ${deploymentProject.default_branch}` : ''}`
                        : undefined
                }
                resourceType={{ type: 'deployments' }}
                actions={
                    <>
                        {deploymentProject?.repo_url && (
                            <LemonButton
                                type="secondary"
                                to={deploymentProject.repo_url}
                                targetBlank
                                sideIcon={<IconGithub />}
                            >
                                View source
                            </LemonButton>
                        )}
                        {liveUrl && (
                            <LemonButton type="primary" to={liveUrl} targetBlank sideIcon={<IconExternal />}>
                                Visit
                            </LemonButton>
                        )}
                    </>
                }
            />

            {currentDeployment && <CurrentDeploymentCard deployment={currentDeployment} />}

            {shouldShowEmptyState ? (
                <LemonBanner type="info">
                    No deployments yet for this project. Push to{' '}
                    <code>{deploymentProject?.default_branch ?? 'the tracked branch'}</code> to trigger one.
                </LemonBanner>
            ) : (
                <>
                    <DeploymentsFilters projectId={projectId} />
                    <LemonTable
                        dataSource={deployments}
                        columns={columns}
                        loading={deploymentsLoading}
                        pagination={pagination}
                        rowKey="id"
                        data-attr="deployments-table"
                    />
                </>
            )}
        </SceneContent>
    )
}

export default DeploymentProject
