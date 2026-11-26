import { TodayRailIconFrame } from './TodayRailIconFrame'

const PULSE = 'M6.75 12.25h2.4l1.6-3.25 2.5 6.5 1.6-3.25h2.4'

export function IconTodayMonitor(): JSX.Element {
    return (
        <TodayRailIconFrame
            name="monitor"
            mask={
                <path
                    className="TodayRailIcon__pulse"
                    pathLength={1}
                    d={PULSE}
                    fill="none"
                    stroke="#000"
                    strokeWidth="1.75"
                />
            }
            line={() => (
                <>
                    <rect x="3.5" y="4.5" width="17" height="15" rx="3.5" />
                    <path className="TodayRailIcon__pulse" pathLength={1} d={PULSE} />
                </>
            )}
            fill={(maskUrl) => (
                <g mask={maskUrl}>
                    <rect x="3.5" y="4.5" width="17" height="15" rx="3.5" />
                </g>
            )}
        />
    )
}
