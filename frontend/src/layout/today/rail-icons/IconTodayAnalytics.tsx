import { TodayRailIconFrame } from './TodayRailIconFrame'

export function IconTodayAnalytics(): JSX.Element {
    return (
        <TodayRailIconFrame
            name="analytics"
            line={() => (
                <>
                    <rect className="TodayRailIcon__bar1" x="3.125" y="13" width="3.75" height="7" rx="1.875" />
                    <rect className="TodayRailIcon__bar2" x="10.125" y="4" width="3.75" height="16" rx="1.875" />
                    <rect className="TodayRailIcon__bar3" x="17.125" y="9" width="3.75" height="11" rx="1.875" />
                </>
            )}
            fill={() => (
                <g stroke="none">
                    <rect className="TodayRailIcon__bar1" x="2.25" y="12.125" width="5.5" height="8.75" rx="2.75" />
                    <rect className="TodayRailIcon__bar2" x="9.25" y="3.125" width="5.5" height="17.75" rx="2.75" />
                    <rect className="TodayRailIcon__bar3" x="16.25" y="8.125" width="5.5" height="12.75" rx="2.75" />
                </g>
            )}
        />
    )
}
