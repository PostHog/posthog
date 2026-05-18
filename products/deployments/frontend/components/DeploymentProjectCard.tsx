import { router } from 'kea-router'

import { IconExternal, IconGithub } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { Deployment, DeploymentProject } from '../fixtures'
import { DeploymentPreviewImage } from './DeploymentPreviewImage'
import { DeploymentStatusTag } from './DeploymentStatusTag'

interface DeploymentProjectCardProps {
    project: DeploymentProject
    currentDeployment: Deployment | null
}

export function DeploymentProjectCard({ project, currentDeployment }: DeploymentProjectCardProps): JSX.Element {
    const repoLabel = project.repo_url.replace('https://github.com/', '')
    const liveUrl = project.subdomain ? `https://${project.subdomain}` : null

    const goToProject = (): void => {
        router.actions.push(urls.deploymentProject(project.id))
    }

    return (
        <LemonCard
            hoverEffect
            onClick={goToProject}
            className="overflow-hidden flex flex-col p-0"
            data-attr={`deployment-project-card-${project.id}`}
        >
            <div className="flex items-start justify-between p-4 gap-2">
                <div className="flex flex-col min-w-0">
                    <span className="font-semibold truncate">{project.name}</span>
                    <span className="text-xs text-secondary truncate">
                        {repoLabel}
                        {project.default_branch ? ` · ${project.default_branch}` : ''}
                    </span>
                </div>
                {currentDeployment ? (
                    <DeploymentStatusTag status={currentDeployment.status} />
                ) : (
                    <LemonTag type="default">Building</LemonTag>
                )}
            </div>

            <DeploymentPreviewImage
                src={currentDeployment?.preview_image_url ?? ''}
                alt={`Preview of ${project.name}`}
                className="aspect-video"
                failed={currentDeployment?.status === 'error'}
            />

            {currentDeployment ? (
                <div className="flex flex-col gap-1 p-4 border-t border-border min-w-0">
                    <span className="text-sm truncate">
                        {currentDeployment.commit_message || currentDeployment.commit_sha || currentDeployment.id}
                    </span>
                    <div className="text-xs text-secondary flex items-center gap-2 min-w-0">
                        <span className="truncate">{currentDeployment.commit_author_name ?? 'Unknown author'}</span>
                        <span>·</span>
                        <TZLabel time={currentDeployment.created_at} />
                    </div>
                </div>
            ) : (
                <div className="flex flex-col gap-1 p-4 border-t border-border">
                    <span className="text-sm text-secondary">No deployments yet</span>
                </div>
            )}

            <div className="flex gap-2 p-4 border-t border-border" onClick={(e) => e.stopPropagation()}>
                <LemonButton type="secondary" size="small" to={project.repo_url} targetBlank sideIcon={<IconGithub />}>
                    View source
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    to={liveUrl || undefined}
                    targetBlank
                    sideIcon={<IconExternal />}
                    disabledReason={!liveUrl ? 'Not yet available' : undefined}
                >
                    Visit
                </LemonButton>
            </div>
        </LemonCard>
    )
}
