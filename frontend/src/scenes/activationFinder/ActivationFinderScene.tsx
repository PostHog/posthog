import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'

export function ActivationFinderScene(): JSX.Element {
    return (
        <div className="ActivationFinderScene">
            <PageHeader title="Activation Finder" />
            <p>
                Use our handy tool to identify some groups of actions that make a good candidate for your product's
                Activation milestone.
            </p>
        </div>
    )
}

export const scene: SceneExport = {
    component: ActivationFinderScene,
}
