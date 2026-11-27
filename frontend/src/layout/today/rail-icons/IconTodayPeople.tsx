import { TodayRailIconFrame } from './TodayRailIconFrame'

const FRONT_BODY = 'M3 19a5.25 5.25 0 0 1 10.5 0 1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z'

export function IconTodayPeople(): JSX.Element {
    return (
        <TodayRailIconFrame
            name="people"
            mask={
                <g fill="#000" stroke="#000" strokeWidth="4.75">
                    <circle className="TodayRailIcon__head" cx="8.25" cy="8" r="3" />
                    <path d={FRONT_BODY} />
                </g>
            }
            line={(maskUrl) => (
                <>
                    <g className="TodayRailIcon__back" mask={maskUrl}>
                        <circle cx="17" cy="7.25" r="2.5" />
                        <path d="M13 18.75a4 4 0 0 1 8 0v.25a1 1 0 0 1-1 1h-6a1 1 0 0 1-1-1z" />
                    </g>
                    <circle className="TodayRailIcon__head" cx="8.25" cy="8" r="3" />
                    <path d={FRONT_BODY} />
                </>
            )}
        />
    )
}
