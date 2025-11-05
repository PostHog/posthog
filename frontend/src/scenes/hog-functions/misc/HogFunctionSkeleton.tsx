import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function HogFunctionSkeleton(): JSX.Element {
    return (
        <div className="flex flex-row flex-wrap gap-4 h-120">
            <div className="flex flex-col flex-1 gap-4 min-w-60">
                <LemonSkeleton className="flex-1 w-full h-full" />
                <LemonSkeleton className="flex-1 w-full h-full" />
            </div>
            <div className="flex flex-col gap-4 flex-2 min-w-60">
                <LemonSkeleton className="flex-1 w-full h-full" />
            </div>
        </div>
    )
}
