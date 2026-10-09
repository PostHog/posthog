// Inline sample data: a canvas is arbitrary app UI, so the preview sketches a small control
// surface rather than importing any canvas runtime.
const SAMPLE_ROWS = [
    { label: 'Beta cohort', value: '1,240 users', action: 'Enable flag' },
    { label: 'Open issues', value: '7 this week', action: 'Assign' },
]

export function CanvasAppWidgetPreview(): JSX.Element {
    return (
        <div className="pointer-events-none flex flex-col gap-2 p-2 shadow-sm">
            <div className="flex items-center justify-between gap-2">
                <span className="truncate font-semibold">Support console</span>
                <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                    Canvas app
                </span>
            </div>
            <div className="flex flex-col divide-y rounded border bg-bg-light/40">
                {SAMPLE_ROWS.map((row) => (
                    <div key={row.label} className="flex items-center justify-between gap-2 px-2 py-1.5">
                        <div className="flex min-w-0 flex-col">
                            <span className="truncate text-sm font-semibold text-primary">{row.label}</span>
                            <span className="truncate text-xs text-muted">{row.value}</span>
                        </div>
                        <span className="shrink-0 rounded border px-2 py-0.5 text-xs font-semibold">{row.action}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}
