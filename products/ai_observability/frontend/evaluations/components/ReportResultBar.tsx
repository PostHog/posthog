import { cn } from 'lib/utils/css-classes'

export interface ReportResultSegment {
    key: string
    label: string
    count: number
}

const RESULT_TONES: Record<string, string> = {
    pass: 'bg-success',
    positive: 'bg-success',
    fail: 'bg-danger',
    negative: 'bg-danger',
}

export function resultTone(key: string): string {
    return RESULT_TONES[key] ?? 'bg-muted'
}

/** One bar split by result, so the share of each outcome reads at a glance. */
export function ReportResultBar({
    segments,
    className,
}: {
    segments: ReportResultSegment[]
    className?: string
}): JSX.Element | null {
    const total = segments.reduce((sum, { count }) => sum + count, 0)
    if (total === 0) {
        return null
    }
    return (
        <div
            className={cn('flex h-1.5 gap-px overflow-hidden rounded-full bg-fill-secondary', className)}
            role="img"
            aria-label={segments.map(({ label, count }) => `${label} ${count}`).join(', ')}
        >
            {segments
                .filter(({ count }) => count > 0)
                .map(({ key, count }) => (
                    <div key={key} className={resultTone(key)} style={{ width: `${(count / total) * 100}%` }} />
                ))}
        </div>
    )
}
