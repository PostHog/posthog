import { TodayRailIconFrame } from './TodayRailIconFrame'

const HOUSE =
    'M4.5 10.2c0-.6.27-1.17.74-1.55l5.5-4.4a2 2 0 0 1 2.52 0l5.5 4.4c.47.38.74.95.74 1.55V18a2.5 2.5 0 0 1-2.5 2.5H7A2.5 2.5 0 0 1 4.5 18z'

export function IconTodayHome(): JSX.Element {
    return (
        <TodayRailIconFrame
            name="home"
            mask={<path d="M10.25 23v-6a1.75 1.75 0 0 1 3.5 0V23z" fill="#000" />}
            line={() => (
                <>
                    <path d={HOUSE} />
                    <path d="M9.75 20.5v-3.75a2.25 2.25 0 0 1 4.5 0v3.75" />
                </>
            )}
            fill={(maskUrl) => (
                <g mask={maskUrl}>
                    <path d={HOUSE} />
                </g>
            )}
        />
    )
}
