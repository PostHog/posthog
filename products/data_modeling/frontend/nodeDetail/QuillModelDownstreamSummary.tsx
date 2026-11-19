import { Button, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { QuillModelFact } from './QuillModelFact'

export function QuillModelDownstreamSummary({
    downstreamCount,
    lineageUrl,
    loading = false,
}: {
    downstreamCount: number
    lineageUrl: string
    loading?: boolean
}): JSX.Element {
    return (
        <QuillModelFact
            label="Downstream"
            hint="Models that depend on this model's results. Open lineage to see how they are connected."
        >
            {loading ? (
                <Skeleton className="h-4 w-32" />
            ) : downstreamCount ? (
                <Button variant="link" size="inline" render={<LinkPrimitive to={lineageUrl} />}>
                    {`${downstreamCount} ${downstreamCount === 1 ? 'model' : 'models'}`}
                </Button>
            ) : (
                'No dependent models'
            )}
        </QuillModelFact>
    )
}
