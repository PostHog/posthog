import { useActions, useValues } from 'kea'
import { CSSProperties } from 'react'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { brandingForProduct } from '../productBranding'
import { welcomeDialogLogic } from '../welcomeDialogLogic'

export function ProductsInUseCard(): JSX.Element | null {
    const { productsInUse } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (productsInUse.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-4">
            <h2 className="text-lg font-semibold mb-1">Products your team uses</h2>
            <p className="text-xs text-muted mb-3 m-0">Click to read the docs.</p>
            <div className="flex flex-wrap gap-2">
                {productsInUse.map((productKey) => {
                    const meta = brandingForProduct(productKey)
                    const Icon = meta.Icon
                    // CSS vars cascade to the Link inside so its tailwind arbitrary values can reference them.
                    const wrapperStyle = { '--brand-rgb': meta.rgb } as CSSProperties
                    return (
                        <div
                            key={productKey}
                            /* eslint-disable-next-line react/forbid-dom-props */
                            style={wrapperStyle}
                            className="inline-flex"
                        >
                            <Link
                                to={meta.docsHref}
                                target="_blank"
                                subtle
                                onClick={() => trackCardClick('products', meta.docsHref)}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-sm bg-[rgb(var(--brand-rgb)/0.08)] border-[rgb(var(--brand-rgb)/0.28)] hover:bg-[rgb(var(--brand-rgb)/0.14)] transition-colors"
                            >
                                <Icon className="text-base text-[rgb(var(--brand-rgb))]" />
                                <span className="font-medium">{meta.label}</span>
                            </Link>
                        </div>
                    )
                })}
            </div>
        </LemonCard>
    )
}
