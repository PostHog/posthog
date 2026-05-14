import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    PaginationManual,
} from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { createdAtColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { CurrentDeploymentCard } from './components/CurrentDeploymentCard'
import { DeploymentsFilters } from './components/DeploymentsFilters'
import { DeploymentStatusTag } from './components/DeploymentStatusTag'
import { deploymentsLogic } from './deploymentsLogic'
import { Deployment, DEPLOYMENTS_PER_PAGE, DeploymentStatus, formatDuration } from './fixtures'

export const scene: SceneExport = {
    component: Deployments,
    logic: deploymentsLogic,
    productKey: ProductKey.DEPLOYMENTS,
}

export function Deployments(): JSX.Element {
    const {
        deployments,
        deploymentsCount,
        deploymentsLoading,
        currentDeployment,
        filters,
        shouldShowEmptyState,
        hasNoProjects,
        deploymentProjects,
        deploymentProjectsLoading,
        selectedProjectId,
    } = useValues(deploymentsLogic)
    const { setFilters, setSelectedProjectId, redeployDeployment, rollbackDeployment } = useActions(deploymentsLogic)

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
                <div className="flex items-center gap-2 min-w-0">
                    <span className="font-semibold truncate">{d.commit_message || d.id}</span>
                    {d.is_current && <LemonTag type="success">Current</LemonTag>}
                </div>
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

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Deployments]?.name ?? 'Deployments'}
                description={
                    sceneConfigurations[Scene.Deployments]?.description ??
                    'View, redeploy, and roll back deployments of your app.'
                }
                resourceType={{ type: 'deployments' }}
            />

            {/* Project picker — top of the page since the card + table below
                are scoped to the currently-selected deployment project. */}
            {!hasNoProjects && deploymentProjects.length > 0 && (
                <div className="flex items-center gap-2">
                    <span className="text-secondary text-sm">Project:</span>
                    <LemonSelect
                        value={selectedProjectId}
                        options={deploymentProjects.map((p) => ({
                            value: p.id,
                            label: p.name,
                        }))}
                        onChange={(id) => setSelectedProjectId(id ?? null)}
                        loading={deploymentProjectsLoading}
                        className="min-w-64"
                        data-attr="deployments-project-switcher"
                    />
                </div>
            )}

            {currentDeployment && <CurrentDeploymentCard deployment={currentDeployment} />}

            <ProductIntroduction
                productName="Deployments"
                productKey={ProductKey.DEPLOYMENTS}
                thingName="deployment"
                description={
                    hasNoProjects
                        ? 'Connect a repo to start deploying. Each push creates a new deployment with its own preview URL.'
                        : 'Track and manage every deployment of your app — see status, duration, who shipped it, and instantly redeploy or roll back.'
                }
                isEmpty={shouldShowEmptyState}
                action={() =>
                    LemonDialog.open({
                        title: 'Connect a repo',
                        description:
                            'Project provisioning (GitHub install, Cloudflare setup) is coming. Once a deployment project exists for your team it shows up here automatically.',
                        primaryButton: { children: 'Got it', type: 'primary' },
                    })
                }
            />

            {!shouldShowEmptyState && (
                <>
                    {selectedProjectId && (
                        <>
                            <DeploymentsFilters />
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
                    {!selectedProjectId && !deploymentProjectsLoading && (
                        <LemonBanner type="info">Pick a deployment project to see its history.</LemonBanner>
                    )}
                </>
            )}
        </SceneContent>
    )
}

export default Deployments
