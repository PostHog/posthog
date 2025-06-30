export function TableHeader(): JSX.Element {
    return (
        <thead>
            <tr>
                <th className="metric-header">Metric</th>
                <th className="baseline-header">Baseline</th>
                <th className="variant-header">Variant</th>
                <th className="chart-header">Chart</th>
            </tr>
        </thead>
    )
}
