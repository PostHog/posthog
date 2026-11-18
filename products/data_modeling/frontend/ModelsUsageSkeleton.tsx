import { Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton, Text } from 'lib/ui/quill'

export function ModelsUsageSkeleton(): JSX.Element {
    return (
        <div role="status" aria-label="Loading model usage" aria-busy="true">
            <div className="space-y-4">
                <div className="grid grid-cols-1 gap-4 @min-[36rem]/main-content:grid-cols-3">
                    {['Bytes read', 'CPU time', 'Runs'].map((title) => (
                        <Card key={title} size="sm" className="min-w-0">
                            <CardContent>
                                <Text size="sm">{title}</Text>
                                <Skeleton className="motion-reduce:animate-none mt-2 h-8 w-32 max-w-full" />
                            </CardContent>
                        </Card>
                    ))}
                </div>
                <div className="grid grid-cols-1 gap-4 @min-[64rem]/main-content:grid-cols-2">
                    {[
                        {
                            title: 'Bytes read by day',
                            description:
                                'Usage is attributed to the day each run finished. Gaps have no measured usage.',
                        },
                        {
                            title: 'Models by latest run status',
                            description: 'Latest run for each model and engine in the selected complete-day range.',
                        },
                    ].map(({ title, description }) => (
                        <Card key={title} size="sm" className="min-w-0">
                            <CardHeader>
                                <CardTitle role="heading" aria-level={3}>
                                    {title}
                                </CardTitle>
                                <CardDescription>{description}</CardDescription>
                            </CardHeader>
                            <CardContent>
                                <Skeleton className="motion-reduce:animate-none h-64 w-full" />
                            </CardContent>
                        </Card>
                    ))}
                </div>
                <Card size="sm" className="min-w-0">
                    <CardHeader>
                        <CardTitle role="heading" aria-level={3}>
                            Usage by model
                        </CardTitle>
                        <CardDescription>
                            Review refresh schedules and query filters for models with high usage.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        {Array.from({ length: 4 }, (_, index) => (
                            <div key={index} className="flex items-center gap-4">
                                <Skeleton className="motion-reduce:animate-none h-4 w-1/2" />
                                <Skeleton className="motion-reduce:animate-none h-4 flex-1" />
                                <Skeleton className="motion-reduce:animate-none h-4 flex-1" />
                            </div>
                        ))}
                    </CardContent>
                </Card>
            </div>
        </div>
    )
}
