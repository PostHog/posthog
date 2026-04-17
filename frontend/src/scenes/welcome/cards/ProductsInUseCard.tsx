import { useActions, useValues } from 'kea'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

const PRODUCT_LABELS: Record<string, { label: string; href: string }> = {
    product_analytics: { label: 'Product analytics', href: '/insights' },
    session_replay: { label: 'Session replay', href: '/replay/home' },
    feature_flags: { label: 'Feature flags', href: '/feature_flags' },
    experiments: { label: 'Experiments', href: '/experiments' },
    surveys: { label: 'Surveys', href: '/surveys' },
    error_tracking: { label: 'Error tracking', href: '/error_tracking' },
    data_warehouse: { label: 'Data warehouse', href: '/data-warehouse' },
    llm_analytics: { label: 'LLM analytics', href: '/llm-analytics' },
    web_analytics: { label: 'Web analytics', href: '/web' },
}

export function ProductsInUseCard(): JSX.Element | null {
    const { productsInUse } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (productsInUse.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-6">
            <h2 className="text-lg font-semibold mb-3">Products your team uses</h2>
            <div className="flex flex-wrap gap-2">
                {productsInUse.map((productKey) => {
                    const entry = PRODUCT_LABELS[productKey]
                    if (!entry) {
                        return null
                    }
                    return (
                        <Link
                            key={productKey}
                            to={entry.href}
                            onClick={() => trackCardClick('products', entry.href)}
                            className="px-3 py-1 rounded-full bg-bg-light border border-border text-sm hover:bg-accent-highlight-secondary"
                        >
                            {entry.label}
                        </Link>
                    )
                })}
            </div>
        </LemonCard>
    )
}
