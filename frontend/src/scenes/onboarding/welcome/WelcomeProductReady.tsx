import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { OnboardingProduct } from '~/types'

import { toSentenceCase } from '../shared/utils'

export function WelcomeProductReady({
    product,
    title,
    description,
}: {
    product: OnboardingProduct
    title?: string
    description?: string
}): JSX.Element {
    const Hedgehog = product.hedgehog
    const name = toSentenceCase(product.name)

    return (
        <div
            className="mx-auto flex max-w-xl flex-col items-center gap-4 py-8 text-center"
            data-attr="onboarding-welcome-product-ready"
        >
            {Hedgehog ? <Hedgehog className="w-40" /> : null}
            <div className="flex flex-col gap-1">
                <h2 className="m-0 text-xl font-semibold">{title ?? name}</h2>
                <p className="m-0 text-secondary">
                    {description ?? product.userCentricDescription ?? product.description}
                </p>
            </div>
            {product.valueProps?.length ? (
                <div className="flex w-full flex-col gap-2 text-left">
                    <span className="text-xs font-semibold text-secondary">What to try first</span>
                    <ul className="m-0 flex list-none flex-col gap-2 p-0">
                        {product.valueProps.map(({ title: valueTitle, problem }) => (
                            <li key={valueTitle} className="flex gap-2 rounded border border-primary p-3">
                                <IconArrowRight className="mt-0.5 shrink-0 text-lg text-secondary" />
                                <div className="flex min-w-0 flex-col">
                                    <span className="font-semibold">{valueTitle}</span>
                                    <span className="text-xs text-secondary">{problem}</span>
                                </div>
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}
            <LemonButton type="primary" to={product.url} data-attr="onboarding-welcome-open-product">
                {`Open ${name}`}
            </LemonButton>
        </div>
    )
}
