interface FlakeScoreBarProps {
    score: number
}

function scoreColor(score: number): string {
    if (score < 0.1) {
        return 'bg-success'
    }
    if (score < 0.3) {
        return 'bg-warning'
    }
    return 'bg-danger'
}

export function FlakeScoreBar({ score }: FlakeScoreBarProps): JSX.Element {
    const widthPercent = Math.min(score * 100, 100)

    return (
        <div className="flex items-center gap-2">
            <div className="w-16 h-1.5 bg-border rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${scoreColor(score)}`} style={{ width: `${widthPercent}%` }} />
            </div>
            <span className="text-xs text-muted font-mono">{(score * 100).toFixed(0)}%</span>
        </div>
    )
}
