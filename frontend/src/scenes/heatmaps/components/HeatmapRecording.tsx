import { BindLogic, useActions, useValues } from 'kea'
import { useRef } from 'react'

import { LemonBanner, LemonDivider, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { FixedReplayHeatmapBrowser } from 'scenes/heatmaps/components/FixedReplayHeatmapBrowser'
import { HeatmapsWarnings } from 'scenes/heatmaps/components/HeatmapsWarnings'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { FilterPanel } from './FilterPanel'
import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

function UrlSearchHeader(): JSX.Element {
    const logic = heatmapsBrowserLogic()
    const { replayIframeData } = useValues(logic)
    const { setReplayIframeDataURL } = useActions(logic)

    return (
        <>
            <div className="flex-none md:flex justify-between items-end gap-2 w-full">
                <div className="flex gap-2 flex-1 min-w-0">
                    <div className="flex-1">
                        <div className="mt-2">
                            <LemonLabel>Heatmap data URL</LemonLabel>
                            <div className="text-xs text-muted mb-1">
                                Add * for wildcards to aggregate data from multiple pages
                            </div>
                            <LemonInput
                                value={replayIframeData?.url}
                                onChange={(s) => setReplayIframeDataURL(s)}
                                className="truncate"
                                size="small"
                            />
                        </div>
                    </div>
                </div>
            </div>
        </>
    )
}

export function HeatmapRecording(): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement | null>(null)

    const logicProps = { ref: iframeRef }

    const logic = heatmapsBrowserLogic({ iframeRef })

    const { hasValidReplayIframeData } = useValues(logic)

    if (!hasValidReplayIframeData) {
        return (
            <LemonBanner type="warning" dismissKey="heatmaps-no-replay-iframe-data-warning">
                <div className="flex items-center justify-between gap-4">
                    <p>This view is based on session recording data. Please open a session recording to view it.</p>
                    <ViewRecordingsPlaylistButton filters={{}} type="secondary" size="small" />
                </div>
            </LemonBanner>
        )
    }

    return (
        <BindLogic logic={heatmapsBrowserLogic} props={logicProps}>
            <SceneContent>
                <HeatmapsWarnings />
                <div className="overflow-hidden w-full min-h-screen">
                    <UrlSearchHeader />
                    <LemonDivider className="my-4" />
                    <FilterPanel />
                    <LemonDivider className="my-4" />
                    <div className="relative flex flex-1 overflow-hidden min-h-screen">
                        <FixedReplayHeatmapBrowser iframeRef={iframeRef} />
                    </div>
                </div>
            </SceneContent>
        </BindLogic>
    )
}
