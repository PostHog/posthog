import type { ReactNode } from 'react'

import { underlinePaths } from './todayPenPaths'

export function TodayPenMark({
    seed,
    delayMs,
    children,
}: {
    seed: string
    delayMs: number
    children: ReactNode
}): JSX.Element {
    return (
        <span className="relative inline-block indent-0 whitespace-nowrap text-[var(--foreground)]">
            {children}
            <svg
                className="TodayPenMark__stroke"
                viewBox="0 0 100 10"
                preserveAspectRatio="none"
                style={{ ['--today-mark-delay' as string]: `${delayMs}ms` }}
                aria-hidden
            >
                {underlinePaths(seed).map((path) => (
                    <path key={path} d={path} pathLength={1} />
                ))}
            </svg>
        </span>
    )
}
