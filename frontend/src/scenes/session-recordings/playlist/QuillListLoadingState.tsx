import { Skeleton } from '@posthog/quill'

import { range } from 'lib/utils/arrays'

export function QuillListLoadingState(): JSX.Element {
    return (
        <div data-quill className="flex flex-col">
            {range(5).map((i) => (
                <div key={i} className="flex flex-col gap-2 p-4">
                    <Skeleton className="w-1/2 h-4" />
                    <Skeleton className="w-1/3 h-4" />
                </div>
            ))}
        </div>
    )
}
