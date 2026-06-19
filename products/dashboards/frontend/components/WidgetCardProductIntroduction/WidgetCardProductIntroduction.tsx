import './WidgetCardProductIntroduction.scss'

import {
    ProductIntroduction,
    type ProductIntroductionProps,
} from 'lib/components/ProductIntroduction/ProductIntroduction'
import { cn } from 'lib/utils/css-classes'

type WidgetCardProductIntroductionProps = Omit<
    ProductIntroductionProps,
    'hogLayout' | 'useMainContentContainerQueries'
> & {
    /** Hog above copy at all tile widths (disables responsive side-by-side layout). */
    stacked?: boolean
}

/**
 * ProductIntroduction tuned for dashboard widget tiles. WidgetCardBody defines
 * `@container/widget-card`; the SCSS wrapper remaps responsive layout from viewport
 * `md:` breakpoints to the widget-card container width.
 */
export function WidgetCardProductIntroduction({
    className,
    contentClassName,
    stacked,
    ...props
}: WidgetCardProductIntroductionProps): JSX.Element | null {
    const isStacked = stacked ?? className?.includes('WidgetCardProductIntroduction--stacked')

    return (
        <div
            className={cn(
                'WidgetCardProductIntroduction',
                isStacked && 'WidgetCardProductIntroduction--stacked',
                className
            )}
        >
            <ProductIntroduction
                {...props}
                contentClassName={cn('max-w-none', contentClassName)}
                hogLayout={isStacked ? 'vertical' : 'responsive'}
            />
        </div>
    )
}
