export function DashboardResizeHandles(): JSX.Element {
    return (
        <div className="handle corner bottom-right">
            <svg
                aria-hidden="true"
                fill="none"
                height="18"
                viewBox="0 0 18 18"
                width="18"
                xmlns="http://www.w3.org/2000/svg"
            >
                <path
                    d="M3 15 15 3M9 15l6-6"
                    opacity="0.5"
                    stroke="var(--color-text-tertiary)"
                    strokeLinecap="round"
                    strokeWidth="1"
                />
            </svg>
        </div>
    )
}
