import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { hedgedHogLogic } from './hedgedHogLogic'

export const scene: SceneExport = {
    component: HedgedHogScene,
    logic: hedgedHogLogic,
}

export function HedgedHogScene(): JSX.Element {
    const { hedgedHogData } = useValues(hedgedHogLogic)

    return (
        <div>
            <PageHeader />
            <div className="border rounded p-4">
                <h2 className="font-semibold text-lg mb-2">Welcome to HedgedHog</h2>
                <p className="mb-4">Welcome to to the future of betting on yourself</p>
                {hedgedHogData && (
                    <div className="mt-4">
                        <h3 className="font-semibold mb-1">Sample Data:</h3>
                        <pre className="p-2 bg-bg-3000 rounded">{JSON.stringify(hedgedHogData, null, 2)}</pre>
                    </div>
                )}
            </div>
        </div>
    )
}
