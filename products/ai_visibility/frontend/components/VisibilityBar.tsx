import clsx from 'clsx'

export function VisibilityBar({ value, max = 100 }: { value: number; max?: number }): JSX.Element {
    const percentage = Math.min(100, (value / max) * 100)
    const getColor = (pct: number): string => {
        if (pct >= 60) {
            return 'bg-[#f54e00]'
        }
        if (pct >= 30) {
            return 'bg-warning'
        }
        return 'bg-danger'
    }

    return (
        <div className="flex items-center gap-2">
            <div className="w-24 h-2 bg-border rounded-full overflow-hidden">
                <div
                    className={clsx('h-full rounded-full', getColor(percentage))}
                    style={{ width: `${percentage}%` }}
                />
            </div>
            <span className="text-sm font-medium w-10">{value}%</span>
        </div>
    )
}
