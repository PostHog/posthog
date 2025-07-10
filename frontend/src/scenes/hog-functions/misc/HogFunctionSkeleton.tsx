import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function HogFunctionSkeleton(): JSX.Element {
    return (
        <div className="h-120 flex flex-row flex-wrap gap-4">
            <div className="flex min-w-60 flex-1 flex-col gap-4">
                <LemonSkeleton className="h-full w-full flex-1" />
                <LemonSkeleton className="h-full w-full flex-1" />
            </div>
            <div className="flex-2 flex min-w-60 flex-col gap-4">
                <LemonSkeleton className="h-full w-full flex-1" />
            </div>
        </div>
    )
}
