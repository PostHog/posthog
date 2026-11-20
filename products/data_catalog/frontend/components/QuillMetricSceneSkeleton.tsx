import { Skeleton } from '@posthog/quill'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

export function QuillMetricSceneSkeleton(): JSX.Element {
    return (
        <SceneContent>
            <div className="flex flex-col gap-4" data-quill>
                <Skeleton className="h-8 w-80 max-w-full" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-9 w-72 max-w-full" />
                <div className="grid max-w-2xl grid-cols-2 gap-x-8 gap-y-3">
                    {Array.from({ length: 4 }, (_, index) => (
                        <Skeleton key={index} className="h-10" />
                    ))}
                </div>
                <Skeleton className="h-64 w-full" />
            </div>
        </SceneContent>
    )
}
