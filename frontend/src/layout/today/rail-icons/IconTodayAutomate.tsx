import { TodayRailIconFrame } from './TodayRailIconFrame'

export function IconTodayAutomate(): JSX.Element {
    return (
        <TodayRailIconFrame
            name="automate"
            line={() => (
                <>
                    <path
                        className="TodayRailIcon__wire"
                        pathLength={1}
                        d="M12 8.25v3.5M6.5 15.25v-1.5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v1.5"
                        fill="none"
                    />
                    <rect x="9.25" y="2.75" width="5.5" height="5.5" rx="1.75" />
                    <circle className="TodayRailIcon__nodeL" cx="6.5" cy="18" r="2.75" />
                    <circle className="TodayRailIcon__nodeR" cx="17.5" cy="18" r="2.75" />
                </>
            )}
        />
    )
}
