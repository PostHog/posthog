import { Heading } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { cn } from 'lib/utils/css-classes'

export function DetailedResultsHeading({
    as: Element = 'h2',
    className,
}: {
    as?: 'h2' | 'span'
    className?: string
}): JSX.Element {
    const quillSurface = useQuillSurface()

    return quillSurface ? (
        <Heading size="base" render={<Element className={cn('m-0', className)} />}>
            Detailed results
        </Heading>
    ) : (
        <Element className={cn('font-semibold text-lg m-0', className)}>Detailed results</Element>
    )
}
