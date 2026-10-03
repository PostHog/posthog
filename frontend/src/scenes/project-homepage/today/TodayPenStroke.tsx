import { underlinePaths } from './todayPenPaths'

/** A hand-drawn underline that fills the width of its positioned parent. */
export function TodayPenStroke({ seed, delayMs = 0 }: { seed: string; delayMs?: number }): JSX.Element {
    return (
        <svg
            className="TodayPen"
            viewBox="0 0 100 10"
            preserveAspectRatio="none"
            style={{ ['--today-mark-delay' as string]: `${delayMs}ms` }}
            aria-hidden
        >
            {underlinePaths(seed).map((path) => (
                <path key={path} d={path} pathLength={1} />
            ))}
        </svg>
    )
}
