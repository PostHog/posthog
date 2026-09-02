import { useValues } from 'kea'

import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'

import { exporterViewLogic } from '../exporterViewLogic'

export default function ExporterHeatmapScene(): JSX.Element {
    const { exportedData, isLoading, screenshotUrl } = useValues(exporterViewLogic)
    const { exportToken } = exportedData
    const width = exportedData.heatmap_context?.width

    return (
        <div
            className="heatmap-exporter relative"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: width ? `${width}px` : '100%',
                minHeight: '100vh',
                overflow: 'hidden',
            }}
        >
            <HeatmapCanvas
                positioning="absolute"
                widthOverride={width ?? null}
                context="in-app"
                exportToken={exportToken}
            />
            {exportedData.heatmap_context?.heatmap_type === 'screenshot' ? (
                isLoading ? null : (
                    <img
                        src={screenshotUrl ?? ''}
                        alt="Heatmap"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: '100%', height: 'auto', display: 'block' }}
                    />
                )
            ) : (
                <iframe
                    id="heatmap-iframe"
                    title="Heatmap export"
                    className="bg-white"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: '100%', height: '100vh', display: 'block' }}
                    src={exportedData.heatmap_url ?? ''}
                    // these two sandbox values are necessary so that the site and toolbar can run
                    // this is a very loose sandbox,
                    // but we specify it so that at least other capabilities are denied
                    sandbox="allow-scripts allow-same-origin"
                    // we don't allow things such as camera access though
                    allow=""
                />
            )}
        </div>
    )
}
