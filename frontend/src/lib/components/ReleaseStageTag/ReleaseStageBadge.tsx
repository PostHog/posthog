import { ComponentProps } from 'react'

import { Badge } from '@posthog/quill'

import { ReleaseStage } from './releaseStage'

const BADGES: Record<ReleaseStage, { label: string; variant: ComponentProps<typeof Badge>['variant'] }> = {
    alpha: { label: 'Alpha', variant: 'completed' },
    beta: { label: 'Beta', variant: 'warning' },
    internal: { label: 'Internal', variant: 'info' },
}

/** The quill mark for a product's release stage. `ReleaseStageTag` is the LemonUI one. */
export function ReleaseStageBadge({ stage }: { stage: ReleaseStage }): JSX.Element {
    const { label, variant } = BADGES[stage]
    return <Badge variant={variant}>{label}</Badge>
}
