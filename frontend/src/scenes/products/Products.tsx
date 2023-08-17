import { LemonButton } from '@posthog/lemon-ui'
import { IconBarChart } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { Product } from '~/types'
import '../products/products.scss'
import { products } from './productsLogic'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

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

function ProductCard({ product }: { product: Product }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const onboardingCompleted = currentTeam?.has_completed_onboarding_for?.[product.key]
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
                {onboardingCompleted ? (
                    <OnboardingCompletedButton productUrl={product.productUrl} onboardingUrl={product.onboardingUrl} />
                ) : (
                    <OnboardingNotCompletedButton url={product.onboardingUrl} />
                )}
            </div>
        </div>
    )
}

export function Products(): JSX.Element {
    return (
        <div className="flex flex-col w-full h-full p-6 items-center justify-center bg-mid">
            <div className="mb-8">
                <h1 className="text-center text-4xl">Let's get started.</h1>
                <p className="text-center">
                    Pick your first product to get started with. You can set up any others you'd like later.
                </p>
            </div>

            <div className="flex w-full max-w-xl justify-center gap-6 flex-wrap">
                {products.map((product) => (
                    <ProductCard product={product} key={product.key} />
                ))}
            </div>
        </div>
    )
}
