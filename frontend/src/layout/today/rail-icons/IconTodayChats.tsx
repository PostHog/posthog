import { TodayRailIconFrame } from './TodayRailIconFrame'

const FRONT =
    'M5.5 9h8a2.5 2.5 0 0 1 2.5 2.5V16a2.5 2.5 0 0 1-2.5 2.5H10L6.5 21v-2.5h-1A2.5 2.5 0 0 1 3 16v-4.5A2.5 2.5 0 0 1 5.5 9z'

export function IconTodayChats(): JSX.Element {
    return (
        <TodayRailIconFrame
            name="chats"
            mask={<path className="TodayRailIcon__front" d={FRONT} fill="#000" stroke="#000" strokeWidth="4.75" />}
            line={(maskUrl) => (
                <>
                    <path
                        className="TodayRailIcon__back"
                        d="M11 3h7.5A2.5 2.5 0 0 1 21 5.5V11a2.5 2.5 0 0 1-2.5 2.5H11A2.5 2.5 0 0 1 8.5 11V5.5A2.5 2.5 0 0 1 11 3z"
                        mask={maskUrl}
                    />
                    <path className="TodayRailIcon__front" d={FRONT} />
                </>
            )}
        />
    )
}
