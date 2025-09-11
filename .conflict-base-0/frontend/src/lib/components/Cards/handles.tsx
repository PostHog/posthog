import clsx from 'clsx'

/** A one-dimensional (either horizontal or vertical) resize handle. */
export function ResizeHandle1D({ orientation }: { orientation: 'horizontal' | 'vertical' }): JSX.Element {
    return (
        <div className={clsx('handle', orientation)}>
            <svg fill="none" height="24" viewBox="0 0 16 24" width="16" xmlns="http://www.w3.org/2000/svg">
                <rect fill="var(--color-bg-surface-primary)" height="23" rx="3.5" width="15" x=".5" y=".5" />
                <g fill="var(--color-accent)">
                    <rect height="2" rx=".25" width="2" x="5" y="5" />
                    <rect height="2" rx=".25" width="2" x="9" y="5" />
                    <rect height="2" rx=".25" width="2" x="5" y="9" />
                    <rect height="2" rx=".25" width="2" x="9" y="9" />
                    <rect height="2" rx=".25" width="2" x="9" y="13" />
                    <rect height="2" rx=".25" width="2" x="9" y="17" />
                    <rect height="2" rx=".25" width="2" x="5" y="13" />
                    <rect height="2" rx=".25" width="2" x="5" y="17" />
                </g>
                <rect height="23" rx="3.5" stroke="var(--color-border-primary)" width="15" x=".5" y=".5" />
            </svg>
        </div>
    )
}

/** A two-dimensional (corner) resize handle. */
export function ResizeHandle2D(): JSX.Element {
    return (
        <div className="handle corner">
            <svg fill="none" height="18" viewBox="0 0 18 18" width="18" xmlns="http://www.w3.org/2000/svg">
                <rect fill="var(--color-bg-surface-primary)" height="17" rx="3.5" width="17" x=".5" y=".5" />
                <g fill="var(--color-accent)">
                    <rect height="2" rx=".25" width="2" x="8" y="8" />
                    <rect height="2" rx=".25" width="2" x="8" y="12" />
                    <rect height="2" rx=".25" width="2" x="12" y="4" />
                    <rect height="2" rx=".25" width="2" x="4" y="12" />
                    <rect height="2" rx=".25" width="2" x="12" y="8" />
                    <rect height="2" rx=".25" width="2" x="12" y="12" />
                </g>
                <rect height="17" rx="3.5" stroke="var(--color-border-primary)" width="17" x=".5" y=".5" />
            </svg>
        </div>
    )
}
