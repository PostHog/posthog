import { LemonSkeleton } from '@posthog/lemon-ui'

import { LemonCard } from 'lib/lemon-ui/LemonCard'

export function PublicationSkeletonCard(): JSX.Element {
    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col gap-2 p-3 h-full rounded-lg border-transparent shadow-sm"
        >
            <LemonSkeleton className="w-full h-24 rounded" />
            <LemonSkeleton className="w-3/4 h-4" />
            <LemonSkeleton className="w-full h-3" />
        </LemonCard>
    )
}
