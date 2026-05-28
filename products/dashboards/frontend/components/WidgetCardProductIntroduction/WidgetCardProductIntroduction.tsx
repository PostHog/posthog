import { ProductIntroduction, type ProductIntroductionProps } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { cn } from 'lib/utils/css-classes'

type WidgetCardProductIntroductionProps = Omit<
    ProductIntroductionProps,
    'hogLayout' | 'useMainContentContainerQueries'
>

/**
 * ProductIntroduction tuned for dashboard widget tiles. WidgetCardBody defines
 * `@container/widget-card`; this wrapper remaps responsive layout from viewport
 * `md:` breakpoints to `@min-[36rem]/widget-card` so setup prompts stack in narrow tiles.
 */
export function WidgetCardProductIntroduction({
    className,
    contentClassName,
    ...props
}: WidgetCardProductIntroductionProps): JSX.Element | null {
    return (
        <div
            className={cn(
                'WidgetCardProductIntroduction',
                '[&_[data-attr^=product-introduction]>div]:flex-col',
                '[&_[data-attr^=product-introduction]>div]:md:flex-col',
                '[&_[data-attr^=product-introduction]>div]:@min-[36rem]/widget-card:flex-row',
                '[&_[data-attr^=product-introduction]>div]:gap-4',
                '[&_[data-attr^=product-introduction]>div]:md:gap-4',
                '[&_[data-attr^=product-introduction]>div]:@min-[36rem]/widget-card:gap-8',
                '[&_[data-attr^=product-introduction]>div>div:first-child]:w-full',
                '[&_[data-attr^=product-introduction]>div>div:first-child]:md:w-full',
                '[&_[data-attr^=product-introduction]>div>div:first-child]:@min-[36rem]/widget-card:w-auto',
                '[&_[data-attr^=product-introduction]>div>div:first-child>div]:mb-4',
                '[&_[data-attr^=product-introduction]>div>div:first-child>div]:md:mb-4',
                '[&_[data-attr^=product-introduction]>div>div:first-child>div]:@min-[36rem]/widget-card:mb-0',
                '[&_[data-attr^=product-introduction]>div>div:last-child]:text-center',
                '[&_[data-attr^=product-introduction]>div>div:last-child]:md:text-center',
                '[&_[data-attr^=product-introduction]>div>div:last-child]:@min-[36rem]/widget-card:text-left',
                '[&_[data-attr^=product-introduction]>div>div:last-child>div:last-child]:justify-center',
                '[&_[data-attr^=product-introduction]>div>div:last-child>div:last-child]:md:justify-center',
                '[&_[data-attr^=product-introduction]>div>div:last-child>div:last-child]:@min-[36rem]/widget-card:justify-start'
            )}
        >
            <ProductIntroduction
                {...props}
                className={className}
                contentClassName={cn('max-w-none', contentClassName)}
                hogLayout="responsive"
            />
        </div>
    )
}
