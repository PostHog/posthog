interface NodeBadgeProps {
    children: React.ReactNode
}

export function NodeBadge({ children }: NodeBadgeProps): JSX.Element {
    return (
        <div className="absolute -top-6 -left-2 bg-bg-light border border-border text-text-3000 font-bold px-4 py-2 rounded-lg shadow-sm text-base z-99999">
            {children}
        </div>
    )
}
