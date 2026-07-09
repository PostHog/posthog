import type { SignalNode } from 'scenes/debug/signals/types'

import { GenericSignalCard } from './components/signalCards/GenericSignalCard'
import { SIGNAL_CARD_REGISTRY } from './components/signalCards/registry'

/**
 * Renders a single signal as evidence in a report/PR detail view. Dispatches to a per-source card
 * via `SIGNAL_CARD_REGISTRY` (first matching entry wins), falling back to `GenericSignalCard` for
 * sources without a dedicated renderer.
 */
export function SignalCard({ signal }: { signal: SignalNode }): JSX.Element {
    const entry = SIGNAL_CARD_REGISTRY.find((candidate) => candidate.matches(signal))
    const Component = entry?.Component ?? GenericSignalCard
    return <Component signal={signal} />
}
