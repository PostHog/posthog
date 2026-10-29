export function HighlightedName({ children }: { children: string }): JSX.Element {
    return (
        <span className="px-1 rounded-md bg-[color-mix(in_srgb,var(--color-blue-500)_10%,transparent)] text-[var(--color-blue-500)]">
            {children}
        </span>
    )
}
