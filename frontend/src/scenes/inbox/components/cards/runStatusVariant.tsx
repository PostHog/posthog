import clsx from 'clsx'

import { LemonTagType } from '@posthog/lemon-ui'

import { SignalScoutRunStatus } from '../../types'

/** The four-bucket lifecycle every run-shaped card collapses its status into. */
export type RunVariant = 'queued' | 'live' | 'completed' | 'failed'

/** Single source of truth mapping a run status to its lifecycle variant. Shared by the card (badge +
 * orb) and the Runs tab (Live vs Past split), so the two can't drift on which statuses are terminal. */
export function resolveRunVariant(status: SignalScoutRunStatus | null): RunVariant {
    switch (status) {
        case 'in_progress':
            return 'live'
        case 'completed':
            return 'completed'
        case 'failed':
        case 'cancelled':
            return 'failed'
        default:
            // queued / not_started / null
            return 'queued'
    }
}

/** Whether a run is still live (running or pending) rather than in a terminal state. */
export function isRunLive(status: SignalScoutRunStatus | null): boolean {
    const variant = resolveRunVariant(status)
    return variant === 'live' || variant === 'queued'
}

export interface VariantMeta {
    label: string
    badgeType: LemonTagType
    orbClass: string
    dotClass: string
    ariaLabel: string
}

export const VARIANT_META: Record<RunVariant, VariantMeta> = {
    queued: {
        label: 'Queued',
        badgeType: 'default',
        orbClass: 'bg-fill-primary ring-primary',
        dotClass: 'bg-muted',
        ariaLabel: 'Queued',
    },
    live: {
        label: 'Running',
        badgeType: 'highlight',
        orbClass: 'bg-primary-highlight ring-primary',
        dotClass: 'bg-accent animate-pulse',
        ariaLabel: 'In progress',
    },
    completed: {
        label: 'Completed',
        badgeType: 'success',
        orbClass: 'bg-success-highlight ring-success',
        dotClass: 'bg-success',
        ariaLabel: 'Completed',
    },
    failed: {
        label: 'Failed',
        badgeType: 'danger',
        orbClass: 'bg-danger-highlight ring-danger',
        dotClass: 'bg-danger',
        ariaLabel: 'Failed',
    },
}

export function RunStatusOrb({ meta }: { meta: VariantMeta }): JSX.Element {
    return (
        <div
            className={clsx(
                'flex items-center justify-center h-7 w-7 shrink-0 rounded-full ring-1 ring-inset',
                meta.orbClass
            )}
        >
            <span
                className={clsx('block h-1.5 w-1.5 rounded-full', meta.dotClass)}
                role="img"
                aria-label={meta.ariaLabel}
            />
        </div>
    )
}
