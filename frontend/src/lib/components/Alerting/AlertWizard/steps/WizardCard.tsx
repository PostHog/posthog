import clsx from 'clsx'

export function WizardCard({
    icon,
    name,
    description,
    badge,
    onClick,
}: {
    icon?: React.ReactNode
    name: string
    description: string
    badge?: string
    onClick: () => void
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'group relative text-left rounded-lg border border-border bg-bg-light transition-all cursor-pointer p-5 w-full',
                'hover:border-border-bold hover:shadow-sm',
                'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2'
            )}
        >
            {badge && <span className="absolute top-3 right-3 text-xs font-medium text-muted">{badge}</span>}
            <div className="flex items-center gap-4">
                {icon && <div className="shrink-0">{icon}</div>}
                <div>
                    <h3 className="font-semibold text-base mb-0.5 transition-colors group-hover:text-link">{name}</h3>
                    <p className="text-secondary text-sm mb-0">{description}</p>
                </div>
            </div>
        </button>
    )
}
