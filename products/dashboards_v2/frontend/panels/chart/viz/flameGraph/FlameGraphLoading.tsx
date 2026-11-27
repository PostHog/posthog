import { Skeleton } from '@posthog/quill'

// Each row's frames as widths, narrowing with depth like a call stack.
const ROWS = [['w-full'], ['w-3/5', 'w-1/3'], ['w-2/5', 'w-1/6', 'w-1/5'], ['w-1/4', 'w-1/12']]

export function FlameGraphLoading(): JSX.Element {
    return (
        <div className="flex min-h-0 flex-1 flex-col gap-0.5" aria-busy="true">
            {ROWS.map((row, depth) => (
                <div key={depth} className="flex gap-0.5">
                    {row.map((widthClass, index) => (
                        <Skeleton key={index} className={`h-5 rounded-sm ${widthClass}`} />
                    ))}
                </div>
            ))}
        </div>
    )
}
