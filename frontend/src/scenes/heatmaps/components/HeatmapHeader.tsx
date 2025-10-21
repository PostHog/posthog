import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { ForbiddenURL } from 'scenes/heatmaps/components/HeatmapsBrowser'
import { heatmapLogic } from 'scenes/heatmaps/scenes/heatmap/heatmapLogic'

import { heatmapsBrowserLogic } from './heatmapsBrowserLogic'

export function HeatmapHeader(): JSX.Element {
    const { dataUrl, displayUrl, isBrowserUrlAuthorized } = useValues(heatmapLogic)

    const { setDataUrl } = useActions(heatmapLogic)
    const { screenshotError } = useValues(heatmapsBrowserLogic)

    return (
        <>
            <div className="flex-none md:flex justify-between items-end gap-2 w-full">
                <div className="flex gap-2 flex-1 min-w-0">
                    <div className="flex-1">
                        <div>
                            <LemonLabel>Heatmap data URL</LemonLabel>
                            <div className="flex gap-2 justify-between">
                                <LemonInput
                                    size="small"
                                    placeholder={displayUrl ? `Same as display URL: ${displayUrl}` : 'Enter a URL'}
                                    value={dataUrl ?? ''}
                                    onChange={(value) => {
                                        setDataUrl(value || null)
                                    }}
                                    fullWidth={true}
                                    disabledReason={!dataUrl ? 'Enter a valid data URL' : undefined}
                                />
                            </div>
                            <div className="text-xs text-muted mt-1">
                                Add * for wildcards to aggregate data from multiple pages
                            </div>
                        </div>
                        {!isBrowserUrlAuthorized ? <ForbiddenURL /> : null}
                        {/* Screenshot display section */}
                        {screenshotError && (
                            <div className="mt-2">
                                <LemonBanner type="error">{screenshotError}</LemonBanner>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </>
    )
}
