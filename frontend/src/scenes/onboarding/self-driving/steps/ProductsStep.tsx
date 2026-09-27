import { useValues } from 'kea'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { toSentenceCase } from 'scenes/onboarding/shared/utils'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { getTreeItemsProducts } from '~/products'

import {
    ADDITIONAL_PRODUCT_DETAILS,
    DOCS_URL_BY_PRODUCT_PATH,
    ONBOARDING_PRODUCTS,
    resolveSetup,
    productIconType,
} from '../../shared/useCases'
import { useCaseSelectionLogic } from '../useCaseSelectionLogic'

export function ProductsStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { selectedUseCase } = useValues(useCaseSelectionLogic)

    const setup = resolveSetup(selectedUseCase)
    const setupProducts = setup.products.map((key) => ONBOARDING_PRODUCTS[key])
    const setupProductKeys = new Set(setupProducts.map((product) => product.productKey))
    const products = [
        ...setupProducts.map((product) => ({
            productKey: product.productKey,
            name: product.displayName ?? product.productPath,
            description: product.benefit,
            docsUrl: DOCS_URL_BY_PRODUCT_PATH[product.productPath],
            iconType: productIconType(product),
        })),
        ...(setup.additionalProducts ?? [])
            .filter((productKey) => !setupProductKeys.has(productKey))
            .map((productKey) => {
                const productItem = getTreeItemsProducts().find((item) => item.intents?.includes(productKey))
                const details = ADDITIONAL_PRODUCT_DETAILS[productKey]
                const product = {
                    name: productItem?.path ?? productKey,
                    description: details?.description ?? '',
                }
                return {
                    productKey,
                    name: toSentenceCase(product.name),
                    description: product.description,
                    docsUrl: details?.docsUrl ?? DOCS_URL_BY_PRODUCT_PATH[product.name],
                    iconType: productItem?.iconType ?? 'product_analytics',
                }
            }),
    ]
    // The setup's sidebar extras, resolved the same way the backend populates the sidebar:
    // through the products registry's `intents`. Products already shown above are excluded.
    const shownNames = new Set(products.map((product) => product.name))
    const sidebarExtras = getTreeItemsProducts().filter(
        (item) =>
            item.intents?.some((intent) => setup.sidebarExtras.includes(intent)) &&
            typeof item.path === 'string' &&
            !shownNames.has(item.path)
    )

    return (
        <div className="flex flex-col gap-6 py-1">
            <p className="text-secondary text-center m-0">
                These products will feed your agents after setup finishes. You can change them later in settings.
            </p>
            <div className="flex flex-col gap-2">
                {products.map((product) => {
                    const iconType = product.iconType
                    const colorVar = `var(--color-product-${iconType.replace(/_/g, '-')}-light)`

                    return (
                        <div
                            key={product.productKey}
                            className="OnboardingProductCard flex items-start gap-4 px-4 rounded-lg"
                        >
                            <div
                                className="size-8 shrink-0 rounded-lg flex items-center justify-center"
                                style={{ background: `color-mix(in srgb, ${colorVar} 12%, transparent)` }}
                            >
                                <div className="flex *:text-xl group/colorful-product-icons colorful-product-icons-true">
                                    {iconForType(iconType)}
                                </div>
                            </div>
                            <div className="flex-1 flex flex-col gap-1 min-w-0">
                                <div className="font-semibold text-base">{product.name}</div>
                                <div className="text-sm text-secondary text-balance">{product.description}</div>
                                <Link to={product.docsUrl} target="_blank" className="text-sm w-fit">
                                    Read the docs
                                </Link>
                            </div>
                        </div>
                    )
                })}
            </div>
            {sidebarExtras.length > 0 && (
                <div className="flex flex-wrap items-center justify-center gap-2">
                    <span className="text-xs text-muted">Also in your sidebar:</span>
                    {sidebarExtras.map((item) => {
                        const tag = (
                            <LemonTag
                                icon={
                                    item.iconType ? (
                                        <span className="flex group/colorful-product-icons colorful-product-icons-true">
                                            {iconForType(item.iconType)}
                                        </span>
                                    ) : undefined
                                }
                            >
                                {item.path}
                            </LemonTag>
                        )
                        const docsUrl = DOCS_URL_BY_PRODUCT_PATH[item.path]
                        return docsUrl ? (
                            <Link key={item.path} to={docsUrl} target="_blank">
                                {tag}
                            </Link>
                        ) : (
                            <span key={item.path}>{tag}</span>
                        )
                    })}
                </div>
            )}
            <div className="flex justify-center">
                <LemonButton type="primary" status="alt" onClick={onContinue}>
                    Continue
                </LemonButton>
            </div>
        </div>
    )
}
