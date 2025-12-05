import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { HeatmapRecording } from 'scenes/heatmaps/components/HeatmapRecording'
import { heatmapRecordingLogic } from 'scenes/heatmaps/scenes/heatmap/heatmapRecordingLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: HeatmapRecordingScene,
    logic: heatmapRecordingLogic,
    settingSectionId: 'environment-autocapture',
}

export function HeatmapRecordingScene(): JSX.Element {
    return (
        <div>
            <LemonBanner
                type="info"
                dismissKey="heatmaps-beta-banner"
                className="mb-4"
                action={{ children: 'Send feedback', id: 'heatmaps-feedback-button' }}
            >
                <p>
                    Heatmaps is in beta. Please let us know what you'd like to see here and/or report any issues
                    directly to us!
                </p>
            </LemonBanner>
            <HeatmapRecording />
        </div>
    )
}
