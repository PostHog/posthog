import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { AddProjectModal } from './components/AddProjectModal'
import { DeploymentProjectCard } from './components/DeploymentProjectCard'
import { deploymentsLogic } from './deploymentsLogic'

export const scene: SceneExport = {
    component: Deployments,
    logic: deploymentsLogic,
    productKey: ProductKey.DEPLOYMENTS,
}

export function Deployments(): JSX.Element {
    const { deploymentProjects, hasNoProjects, currentDeploymentsByProject } = useValues(deploymentsLogic)
    const { openAddProjectModal } = useActions(deploymentsLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.Deployments]?.name ?? 'Deployments'}
                description={
                    sceneConfigurations[Scene.Deployments]?.description ??
                    'Connect a GitHub repository to start deploying your site.'
                }
                resourceType={{ type: 'deployments' }}
                actions={
                    !hasNoProjects && (
                        <LemonButton
                            type="primary"
                            size="small"
                            sideIcon={<IconGithub />}
                            onClick={() => openAddProjectModal()}
                            data-attr="add-deployment-project"
                        >
                            Add project
                        </LemonButton>
                    )
                }
            />

            {hasNoProjects ? (
                <ProductIntroduction
                    productName="Deployments"
                    productKey={ProductKey.DEPLOYMENTS}
                    thingName="deployment project"
                    description="Connect a GitHub repo to deploy a static site through PostHog. Each push creates a new deployment with its own preview URL."
                    isEmpty
                    action={() => openAddProjectModal()}
                    actionElementOverride={
                        <LemonButton
                            type="primary"
                            sideIcon={<IconGithub />}
                            onClick={() => openAddProjectModal()}
                            data-attr="add-deployment-project-empty"
                        >
                            Connect a GitHub repository
                        </LemonButton>
                    }
                />
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {deploymentProjects.map((p) => (
                        <DeploymentProjectCard
                            key={p.id}
                            project={p}
                            currentDeployment={currentDeploymentsByProject[p.id] ?? null}
                        />
                    ))}
                </div>
            )}

            <AddProjectModal />
        </SceneContent>
    )
}

export default Deployments
