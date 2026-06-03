import './WidgetCardProductIntroduction.scss'

import {
    ProductIntroduction,
    type ProductIntroductionProps,
} from 'lib/components/ProductIntroduction/ProductIntroduction'
import { cn } from 'lib/utils/css-classes'

type WidgetCardProductIntroductionProps = Omit<ProductIntroductionProps, 'hogLayout' | 'useMainContentContainerQueries'>

/**
 * ProductIntroduction tuned for dashboard widget tiles. WidgetCardBody defines
 * `@container/widget-card`; the SCSS wrapper remaps responsive layout from viewport
 * `md:` breakpoints to the widget-card container width.
 */
export function WidgetCardProductIntroduction({
    className,
    contentClassName,
    ...props
}: WidgetCardProductIntroductionProps): JSX.Element | null {
    return (
        <div className={cn('WidgetCardProductIntroduction', className)}>
            <ProductIntroduction
                {...props}
                contentClassName={cn('max-w-none', contentClassName)}
                hogLayout="responsive"
            />
        </div>
    )
}
