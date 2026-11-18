export type DotState = 'on' | 'partial' | 'off'

/** How much a setting covers: a filled circle for everything, an open one for part of it, grey for nothing. */
export function StateDot({ state }: { state: DotState }): JSX.Element {
    return (
        <span className={`inline-flex shrink-0 ${state === 'off' ? 'text-border-bold' : 'text-success'}`} aria-hidden>
            <svg width="12" height="12" viewBox="0 0 12 12">
                {state === 'partial' ? (
                    <circle cx="6" cy="6" r="4.75" fill="none" stroke="currentColor" strokeWidth="1.5" />
                ) : (
                    <circle cx="6" cy="6" r="5.5" fill="currentColor" />
                )}
            </svg>
        </span>
    )
}
