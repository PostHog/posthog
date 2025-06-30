export function TableHeader(): JSX.Element {
    return (
        <thead>
            <tr>
                <th className="w-1/4 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Metric
                </th>
                <th className="w-1/5 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Baseline
                </th>
                <th className="w-1/5 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Variant
                </th>
                <th className="w-2/5 min-w-[300px] border-b-2 border-border bg-bg-table p-3 text-center text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Chart
                </th>
            </tr>
        </thead>
    )
}
