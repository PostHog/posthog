import { Card, CardContent, CardHeader, Skeleton } from 'lib/ui/quill'

export function ModelsUsageSkeleton(): JSX.Element {
    return (
        <div role="status" aria-label="Loading model usage" aria-busy="true">
            <div className="space-y-4" aria-hidden="true">
                <div className="grid grid-cols-1 gap-4 @min-[36rem]/main-content:grid-cols-3">
                    {Array.from({ length: 3 }, (_, index) => (
                        <Card key={index} size="sm" className="min-w-0">
                            <CardContent>
                                <Skeleton className="motion-reduce:animate-none h-4 w-20" />
                                <Skeleton className="motion-reduce:animate-none mt-2 h-8 w-32 max-w-full" />
                            </CardContent>
                        </Card>
                    ))}
                </div>
                <div className="grid grid-cols-1 gap-4 @min-[64rem]/main-content:grid-cols-2">
                    {Array.from({ length: 2 }, (_, index) => (
                        <Card key={index} size="sm" className="min-w-0">
                            <CardHeader>
                                <Skeleton className="motion-reduce:animate-none h-5 w-48 max-w-full" />
                                <Skeleton className="motion-reduce:animate-none h-4 w-3/4" />
                            </CardHeader>
                            <CardContent>
                                <Skeleton className="motion-reduce:animate-none h-64 w-full" />
                            </CardContent>
                        </Card>
                    ))}
                </div>
                <Card size="sm" className="min-w-0">
                    <CardHeader>
                        <Skeleton className="motion-reduce:animate-none h-5 w-32" />
                        <Skeleton className="motion-reduce:animate-none h-4 w-3/4" />
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
