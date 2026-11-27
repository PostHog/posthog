import { LemonSkeleton } from '@posthog/lemon-ui'

export function DashboardTemplateItemSkeleton(): JSX.Element {
    return (
        <div
            className="border rounded TemplateItem flex flex-col pointer-events-none select-none w-full h-[210px]"
            aria-hidden
        >
            <div className="h-30 min-h-30 w-full overflow-hidden">
                <LemonSkeleton className="h-30 w-full rounded-none" />
            </div>
            <div className="px-2 py-1">
                <div className="mb-1">
                    <LemonSkeleton className="h-5 w-4/5" />
                </div>
                <div className="py-1 grow flex flex-col gap-1">
                    <LemonSkeleton className="h-3 w-full" />
                    <LemonSkeleton className="h-3 w-[92%]" />
                </div>
            </div>
        </div>
    )
}
