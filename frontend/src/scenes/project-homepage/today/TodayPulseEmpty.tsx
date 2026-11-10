const SLOTS = ['first', 'second', 'third', 'fourth']

export function TodayPulseEmpty(): JSX.Element {
    return (
        <div className="TodayPulseEmpty" data-attr="today-pulse-empty">
            <ul className="TodayPulse TodayPulse--empty" aria-label="No key numbers yet">
                {SLOTS.map((slot) => (
                    <li key={slot} className="TodayPulse__metric TodayPulse__emptySlot" />
                ))}
            </ul>
        </div>
    )
}
