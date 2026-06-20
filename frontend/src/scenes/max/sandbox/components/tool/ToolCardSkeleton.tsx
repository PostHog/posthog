import { Spinner } from '@posthog/lemon-ui'

/**
 * Eager, dependency-light placeholder shown while a tool renderer's lazy chunk loads. A single
 * ToolRow-style header line (registry icon + name + spinner, no body) — must not import
 * `SandboxToolRow` or any heavy renderer, or it would defeat the code split it stands in for.
 */
export function ToolCardSkeleton({ icon, displayName }: { icon?: JSX.Element; displayName?: string }): JSX.Element {
    return (
        <div className="flex items-center gap-1.5 min-w-0 text-[13px] py-0.5">
            <span className="flex items-center justify-center size-3.5 shrink-0 text-muted [&_svg]:size-3.5">
                {icon}
            </span>
            <span className="text-secondary truncate">{displayName ?? 'Tool'}</span>
            <Spinner className="size-3 shrink-0" />
        </div>
    )
}
