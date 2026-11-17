import { IconGithub } from '@posthog/icons'

export function GitHubAccountCard({
    title,
    hint,
    actions,
}: {
    title: React.ReactNode
    hint: React.ReactNode
    actions?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-3 rounded border border-primary bg-surface-primary px-4 py-2.5">
            <IconGithub className="size-6 shrink-0" />
            <div className="flex min-w-0 flex-1 basis-72 flex-col gap-0.5">
                <div className="flex flex-wrap items-center gap-2">{title}</div>
                <span className="text-xs text-secondary">{hint}</span>
            </div>
            {actions && <div className="flex flex-wrap items-center gap-1">{actions}</div>}
        </div>
    )
}
