import { LemonBanner } from '@posthog/lemon-ui'

export function ProductToursDeprecationBanner(): JSX.Element {
    return (
        <LemonBanner
            type="warning"
            action={{
                children: 'Read the guide',
                to: 'https://posthog.com/docs/product-tours/creating-product-tours',
                targetBlank: true,
                // pinned: data-attr for autocapture, renaming breaks the click count
                'data-attr': 'product-tours-deprecation-guide',
            }}
        >
            <strong>Product tours is deprecated and will be removed.</strong> To build tours in your own code with
            feature flags, use the <code>creating-product-tours</code> skill. Run{' '}
            <code>npx @posthog/wizard@latest skill creating-product-tours</code> and the setup agent builds the tour for
            you.
        </LemonBanner>
    )
}
