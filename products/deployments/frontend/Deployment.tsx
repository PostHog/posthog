import { Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

export const scene: SceneExport = {
    component: Deployment,
}

export function Deployment(): JSX.Element {
    return (
        <SceneContent>
            <div className="flex flex-col gap-2">
                {/* TODO(deployments-v1): load the deployment by id (URL param) and render its details. */}
                <h2>Deployment</h2>
                <p>Deployment details are not implemented yet.</p>
                <Link to={urls.deployments()}>Back to deployments</Link>
            </div>
        </SceneContent>
    )
}

export default Deployment
