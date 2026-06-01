import {
    ProductIntroduction,
    type ProductIntroductionProps,
} from 'lib/components/ProductIntroduction/ProductIntroduction'
import { cn } from 'lib/utils/css-classes'

type WidgetCardProductIntroductionProps = Omit<
    ProductIntroductionProps,
    'hogLayout' | 'useMainContentContainerQueries' | 'useWidgetCardContainerQueries'
>

/**
 * ProductIntroduction tuned for dashboard widget tiles. WidgetCardBody defines
 * `@container/widget-card`; this wrapper enables container-query breakpoints for narrow tiles.
 */
export function WidgetCardProductIntroduction({
    className,
    contentClassName,
    ...props
}: WidgetCardProductIntroductionProps): JSX.Element | null {
    return (
        <ProductIntroduction
            {...props}
            className={className}
            contentClassName={cn('max-w-none', contentClassName)}
            hogLayout="responsive"
            useWidgetCardContainerQueries
        />
    )
}
