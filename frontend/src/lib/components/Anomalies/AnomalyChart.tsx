import { useChart } from 'lib/hooks/useChart'

import { AnomalyScoreType } from './types'

interface AnomalySparklineProps {
    anomaly: AnomalyScoreType
}

export function AnomalySparkline({ anomaly }: AnomalySparklineProps): JSX.Element {
    const { data, anomaly_index } = anomaly.data_snapshot

    const { canvasRef } = useChart({
        getConfig: () => ({
            type: 'line' as const,
            data: {
                labels: data.map((_, i) => String(i)),
                datasets: [
                    {
                        data,
                        borderColor: 'rgba(99, 102, 241, 0.8)',
                        borderWidth: 1.5,
                        pointRadius: data.map((_, i) => (i === anomaly_index ? 4 : 0)),
                        pointBackgroundColor: data.map((_, i) =>
                            i === anomaly_index ? 'rgba(220, 38, 38, 0.9)' : 'transparent'
                        ),
                        pointBorderColor: data.map((_, i) =>
                            i === anomaly_index ? 'rgba(153, 27, 27, 1)' : 'transparent'
                        ),
                        pointBorderWidth: data.map((_, i) => (i === anomaly_index ? 1 : 0)),
                        fill: false,
                        tension: 0.3,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false },
                },
                scales: {
                    x: { display: false },
                    y: { display: false },
                },
                elements: {
                    line: { borderWidth: 1.5 },
                },
            },
        }),
        deps: [data, anomaly_index],
    })

    return (
        <div className="w-[120px] h-[32px]">
            <canvas ref={canvasRef} />
        </div>
    )
}
