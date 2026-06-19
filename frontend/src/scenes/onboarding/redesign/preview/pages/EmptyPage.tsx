import { IconGraph } from '@posthog/icons'

/** Skeleton/empty state for the preview, used before the user has configured anything. */
export function EmptyPage({ title, subtitle }: { title?: string; subtitle?: string }): JSX.Element {
    return (
        <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <span className="text-muted flex h-12 w-12 items-center justify-center rounded-xl bg-surface-secondary text-2xl">
                <IconGraph />
            </span>
            <div>
                <div className="font-semibold text-default">{title ?? 'Your workspace'}</div>
                {subtitle && <div className="text-muted mt-1 text-sm">{subtitle}</div>}
            </div>
        </div>
    )
}
