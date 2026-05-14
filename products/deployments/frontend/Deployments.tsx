import { BindLogic } from 'kea'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { CurrentDeploymentCard } from './components/CurrentDeploymentCard'
import { DeploymentsFilters } from './components/DeploymentsFilters'
import { deploymentsLogic } from './deploymentsLogic'

export const scene: SceneExport = {
    component: Deployments,
    logic: deploymentsLogic,
    productKey: ProductKey.DEPLOYMENTS,
}

export function Deployments({ tabId }: { tabId?: string } = {}): JSX.Element {
    return (
        <BindLogic logic={deploymentsLogic} props={{ tabId: tabId ?? '' }}>
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.Deployments].name}
                    description={sceneConfigurations[Scene.Deployments].description}
                    resourceType={{
                        type: sceneConfigurations[Scene.Deployments].iconType || 'deployments',
                    }}
                />
                {/* TODO(deployments-v1): render <CurrentDeploymentCard/> with the team's currently-serving deployment. */}
                <CurrentDeploymentCard />
                {/* TODO(deployments-v1): render <DeploymentsFilters/> with status / author / search controls. */}
                <DeploymentsFilters />
                <ProductIntroduction
                    productName="Deployments"
                    productKey={ProductKey.DEPLOYMENTS}
                    thingName="deployment"
                    description="Build and ship your project site straight from PostHog. Each push creates a deployment with its own preview URL."
                    isEmpty
                />
                {/* TODO(deployments-v1): replace ProductIntroduction with a LemonTable of deployments. */}
            </SceneContent>
        </BindLogic>
    )
}

export default Deployments
