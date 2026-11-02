import type { SearchPoint } from '../agentSearch'

/** How an experiment's status reads to people. A kept experiment improved on the one before it. */
export const EXPERIMENT_STATUS: Record<
    SearchPoint['status'],
    { type: 'success' | 'default' | 'danger'; label: string; color: string; dotClassName: string }
> = {
    kept: { type: 'success', label: 'Improved', color: 'var(--success)', dotClassName: 'bg-success' },
    discarded: { type: 'default', label: 'No gain', color: 'var(--color-text-secondary)', dotClassName: 'bg-muted' },
    crashed: { type: 'danger', label: 'Crashed', color: 'var(--danger)', dotClassName: 'bg-danger' },
}
