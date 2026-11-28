import { TodayRailIconFrame } from './TodayRailIconFrame'

const POLE = 'M6 3.5v17'
const CLOTH = 'M6 4.5h11.25l-2.25 4 2.25 4H6z'

export function IconTodayRelease(): JSX.Element {
    return (
        <TodayRailIconFrame
            name="release"
            line={() => (
                <>
                    <path d={POLE} />
                    <path className="TodayRailIcon__cloth" d={CLOTH} />
                </>
            )}
            fill={() => (
                <>
                    <path d={POLE} fill="none" />
                    <path className="TodayRailIcon__cloth" d={CLOTH} />
                </>
            )}
        />
    )
}
