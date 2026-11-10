import { TodayEmptyPanel } from './TodayEmptyPanel'

const TILES = [
    { key: 'first', name: 'w-3/5', value: 'w-12' },
    { key: 'second', name: 'w-2/5', value: 'w-10' },
    { key: 'third', name: 'w-1/2', value: 'w-9' },
    { key: 'fourth', name: 'w-2/5', value: 'w-14' },
]

export function TodayPulseEmpty(): JSX.Element {
    return (
        <TodayEmptyPanel
            message="Your key numbers show here once PostHog has a few days of data."
            dataAttr="today-pulse-empty"
        >
            <ul className="TodayPulse">
                {TILES.map((tile) => (
                    <li key={tile.key} className="TodayPulse__metric TodayPulseEmpty__tile">
                        <span className={`TodayEmptyPanel__bar TodayPulseEmpty__name ${tile.name}`} />
                        <span className="TodayPulseEmpty__row">
                            <span className={`TodayEmptyPanel__bar TodayPulseEmpty__value ${tile.value}`} />
                            <span className="TodayEmptyPanel__bar TodayPulseEmpty__change" />
                        </span>
                    </li>
                ))}
            </ul>
        </TodayEmptyPanel>
    )
}
