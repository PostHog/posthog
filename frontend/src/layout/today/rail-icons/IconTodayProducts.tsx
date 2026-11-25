import { TodayRailIconFrame } from './TodayRailIconFrame'

function Tiles(): JSX.Element {
    return (
        <>
            <rect className="TodayRailIcon__tile1" x="3.5" y="3.5" width="7" height="7" rx="2" />
            <rect className="TodayRailIcon__tile2" x="13.5" y="3.5" width="7" height="7" rx="2" />
            <rect className="TodayRailIcon__tile3" x="3.5" y="13.5" width="7" height="7" rx="2" />
        </>
    )
}

export function IconTodayProducts(): JSX.Element {
    return (
        <TodayRailIconFrame
            name="products"
            mask={<circle className="TodayRailIcon__lens" cx="16.75" cy="16.75" r="1.6" fill="#000" />}
            line={() => (
                <>
                    <Tiles />
                    <g className="TodayRailIcon__lens">
                        <circle cx="16.75" cy="16.75" r="3.25" />
                        <path d="m19.25 19.25 1.75 1.75" />
                    </g>
                </>
            )}
            fill={(maskUrl) => (
                <>
                    <Tiles />
                    <g className="TodayRailIcon__lens" mask={maskUrl}>
                        <circle cx="16.75" cy="16.75" r="3.25" />
                        <path d="m19.25 19.25 1.75 1.75" fill="none" strokeWidth="2.25" />
                    </g>
                </>
            )}
        />
    )
}
