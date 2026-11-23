export function TaggerConfigField({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="space-y-1">
            <div className="font-semibold">{label}</div>
            {children}
        </div>
    )
}
