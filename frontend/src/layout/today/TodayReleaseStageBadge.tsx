import { Badge } from '@posthog/quill'

import { ReleaseStageProduct, releaseStage } from 'lib/components/ReleaseStageTag/releaseStage'

const STAGES = {
    alpha: { label: 'Alpha', variant: 'completed' },
    beta: { label: 'Beta', variant: 'warning' },
} as const

/** Marks an alpha or beta product in the products pane. Unreleased products sit in their own group, so they get no badge. */
export function TodayReleaseStageBadge({ product }: { product: ReleaseStageProduct }): JSX.Element | null {
    const stage = releaseStage(product)
    if (stage !== 'alpha' && stage !== 'beta') {
        return null
    }
    const { label, variant } = STAGES[stage]
    return <Badge variant={variant}>{label}</Badge>
}
