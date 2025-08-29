import { ChartParams } from '~/types'

import { useFunnelData } from './DataDrivenFunnel'

export function DataDrivenFunnelHistogram({ 
    showPersonsModal: showPersonsModalProp = true 
}: ChartParams): JSX.Element {
    const { histogramGraphData } = useFunnelData()
    const showPersonsModal = showPersonsModalProp

    if (!histogramGraphData || histogramGraphData.length === 0) {
        return (
            <div className="FunnelHistogram" data-attr="funnel-histogram">
                <div className="FunnelHistogram--empty">
                    No time-to-convert data available
                </div>
            </div>
        )
    }

    const maxCount = Math.max(...histogramGraphData.map(bin => bin.count))

    return (
        <div className="FunnelHistogram" data-attr="funnel-histogram">
            <div className="FunnelHistogram--title">
                Time to Convert Distribution
            </div>
            
            <div className="FunnelHistogram--chart">
                <div className="FunnelHistogram--bars">
                    {histogramGraphData.map((bin, index) => (
                        <div 
                            key={bin.id} 
                            className="FunnelHistogram--bar"
                            style={{
                                height: `${(bin.count / maxCount) * 100}%`,
                                backgroundColor: `hsl(210, 70%, ${50 + (index % 2) * 20}%)`,
                            }}
                            title={`${bin.bin0}-${bin.bin1}s: ${bin.count} conversions (${bin.label})`}
                        >
                            <div className="FunnelHistogram--bar-label">
                                {bin.label}
                            </div>
                        </div>
                    ))}
                </div>
                
                <div className="FunnelHistogram--x-axis">
                    {histogramGraphData.map((bin, index) => (
                        <div key={bin.id} className="FunnelHistogram--x-label">
                            {index === 0 ? `${bin.bin0}s` : 
                             index === histogramGraphData.length - 1 ? `${bin.bin1}s` : ''}
                        </div>
                    ))}
                </div>
            </div>

            <div className="FunnelHistogram--legend">
                <p>Distribution of time taken for users to convert through the funnel</p>
            </div>
        </div>
    )
}