import { LemonButton } from '@posthog/lemon-ui'
import { IconBarChart } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { ProductKey } from '~/types'
import '../products/products.scss'

export const scene: SceneExport = {
    component: Products,
    // logic: featureFlagsLogic,
}

function OnboardingCompletedButton({
    productUrl,
    onboardingUrl,
}: {
    productUrl: string
    onboardingUrl: string
}): JSX.Element {
    return (
        <>
            <LemonButton type="secondary" status="muted" to={productUrl}>
                Go to product
            </LemonButton>
            <LemonButton type="tertiary" status="muted" to={onboardingUrl}>
                Set up again
            </LemonButton>
        </>
    )
}

function OnboardingNotCompletedButton({ url }: { url: string }): JSX.Element {
    return (
        <LemonButton type="primary" to={url}>
            Get started
        </LemonButton>
    )
}

function ProductCard({ product }): JSX.Element {
    return (
        <div
            className={`ProductCard border border-border rounded-lg p-6 max-w-80 flex flex-col bg-white`}
            key={product.key}
        >
            <div className="flex mb-2">
                <div className="bg-mid rounded p-1 flex">
                    <IconBarChart className="w-6 h-6" />
                </div>
            </div>
            <div className="mb-2">
                <h3 className="bold mb-0">{product.name}</h3>
            </div>
            <p className="grow">{product.description}</p>
            <div className="flex gap-x-2">
                {product.omboardingCompleted ? (
                    <OnboardingCompletedButton productUrl={product.productUrl} onboardingUrl={product.onboardingUrl} />
                ) : (
                    <OnboardingNotCompletedButton url={product.onboardingUrl} />
                )}
            </div>
        </div>
    )
}

export function Products(): JSX.Element {
    const products = [
        {
            name: 'Product analytics',
            key: ProductKey.PRODUCT_ANALYTICS,
            description: 'Understand your users with trends, funnels, path analysis + more.',
            omboardingCompleted: true,
            productUrl: urls.dashboards(),
            onboardingUrl: urls.ingestion(),
        },
        {
            name: 'Session replay',
            key: ProductKey.SESSION_REPLAY,
            description:
                'Searchable recordings of people using your app or website with console logs and behavioral bucketing.',
            omboardingCompleted: false,
            productUrl: urls.replay(),
            onboardingUrl: urls.ingestion(),
        },
        {
            name: 'Feature flags & A/B testing',
            key: ProductKey.FEATURE_FLAGS,
            description: 'Safely roll out new features and run experiments on changes.',
            omboardingCompleted: false,
            productUrl: urls.featureFlags(),
            onboardingUrl: urls.ingestion(),
        },
        {
            name: 'Data warehouse',
            key: ProductKey.DATA_WAREHOUSE,
            description: 'Bring your production database, revenue data, CRM contacts or any other data into PostHog.',
            omboardingCompleted: true,
            productUrl: urls.dataWarehouse(),
            onboardingUrl: urls.ingestion(),
        },
    ]

    return (
        <div className="flex flex-col w-full h-full p-6 items-center justify-center bg-mid">
            <div className="mb-8">
                <h1 className="text-center text-4xl">Let's get started.</h1>
                <p>Pick your first product to get started with. You can set up any others you'd like later.</p>
            </div>

            <div className="flex w-full max-w-200 justify-center gap-6 flex-wrap">
                {products.map((product) => (
                    <ProductCard product={product} key={product.key} />
                ))}
            </div>
        </div>
    )
}
