export interface SavedViewFiltersSummaryLine {
    label: string
    value: string
}

export type GetSavedViewFiltersSummaryLines = (filters: Record<string, any>) => SavedViewFiltersSummaryLine[]

interface SavedViewFiltersSummaryProps {
    filters: Record<string, any>
    getFiltersSummaryLines: GetSavedViewFiltersSummaryLines
}

export function SavedViewFiltersSummary({
    filters,
    getFiltersSummaryLines,
}: SavedViewFiltersSummaryProps): JSX.Element {
    const lines = getFiltersSummaryLines(filters)
    if (lines.length === 0) {
        return <span className="text-muted text-xs">No filters</span>
    }
    return (
        <div className="text-xs text-muted space-y-0.5">
            {lines.map((line) => (
                <div key={line.label}>
                    <span className="font-medium">{line.label}:</span> {line.value}
                </div>
            ))}
        </div>
    )
}
