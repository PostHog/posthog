import { LemonSkeleton } from '@posthog/lemon-ui'

import { range } from 'lib/utils/arrays'

export function ListLoadingState(): JSX.Element {
    return (
        <>
            {range(5).map((i) => (
                <div key={i} className="p-4 deprecated-space-y-2">
                    <LemonSkeleton className="w-1/2 h-4" />
                    <LemonSkeleton className="w-1/3 h-4" />
                </div>
            ))}
        </>
    )
}
