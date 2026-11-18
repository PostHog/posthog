import { Card, CardContent, Skeleton } from '@posthog/quill'

export function QuillPayGateSkeleton({ className }: { className?: string }): JSX.Element {
    return (
        <Card className={className}>
            <CardContent className="flex flex-col items-center gap-2">
                <Skeleton className="h-10 w-20" />
                <Skeleton className="h-6 w-48" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-8 w-32" />
            </CardContent>
        </Card>
    )
}
