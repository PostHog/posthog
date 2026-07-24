export function HeaderStat({ icon, children }: { icon: JSX.Element; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center gap-1.5 text-sm text-secondary">
            <span className="text-base leading-none">{icon}</span>
            {children}
        </div>
    )
}
