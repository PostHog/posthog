import { TodayRailIconFrame } from './TodayRailIconFrame'

export function IconTodayData(): JSX.Element {
    return (
        <TodayRailIconFrame
            name="data"
            line={() => (
                <>
                    <path
                        className="TodayRailIcon__cap"
                        d="M5 6.25c0-1.52 3.13-2.75 7-2.75s7 1.23 7 2.75v11.5c0 1.52-3.13 2.75-7 2.75s-7-1.23-7-2.75z"
                    />
                    <path className="TodayRailIcon__rim" d="M5 6.25c0 1.52 3.13 2.75 7 2.75s7-1.23 7-2.75" />
                    <path className="TodayRailIcon__band" d="M5 12c0 1.52 3.13 2.75 7 2.75S19 13.52 19 12" />
                </>
            )}
            fill={() => (
                <g stroke="none">
                    <ellipse className="TodayRailIcon__cap" cx="12" cy="6.25" rx="7.875" ry="3.5" />
                    <path
                        className="TodayRailIcon__rim"
                        d="M4.125 7.95A7.875 3.5 0 0 0 19.875 7.95V11.95A7.875 3.5 0 0 1 4.125 11.95z"
                    />
                    <path
                        className="TodayRailIcon__band"
                        d="M4.125 13.65A7.875 3.5 0 0 0 19.875 13.65V17.6A7.875 3.5 0 0 1 4.125 17.6z"
                    />
                </g>
            )}
        />
    )
}
