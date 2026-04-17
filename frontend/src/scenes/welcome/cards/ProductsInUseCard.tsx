import { useActions, useValues } from 'kea'
import { ComponentType, SVGProps } from 'react'

import {
    IconDashboard,
    IconDatabase,
    IconFlag,
    IconFlask,
    IconGraph,
    IconLlmAnalytics,
    IconMessage,
    IconPieChart,
    IconRewindPlay,
    IconWarning,
} from '@posthog/icons'

import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { Link } from 'lib/lemon-ui/Link'

import { welcomeDialogLogic } from '../welcomeDialogLogic'

type IconElement = ComponentType<SVGProps<SVGSVGElement> & { className?: string }>

interface ProductMeta {
    label: string
    docsHref: string
    Icon: IconElement
    iconColor: string
}

const PRODUCT_META: Record<string, ProductMeta> = {
    product_analytics: {
        label: 'Product analytics',
        docsHref: 'https://posthog.com/docs/product-analytics',
        Icon: IconGraph,
        iconColor: 'text-[var(--color-brand-blue)]',
    },
    session_replay: {
        label: 'Session replay',
        docsHref: 'https://posthog.com/docs/session-replay',
        Icon: IconRewindPlay,
        iconColor: 'text-[var(--color-brand-yellow)]',
    },
    feature_flags: {
        label: 'Feature flags',
        docsHref: 'https://posthog.com/docs/feature-flags',
        Icon: IconFlag,
        iconColor: 'text-[var(--color-brand-blue)]',
    },
    experiments: {
        label: 'Experiments',
        docsHref: 'https://posthog.com/docs/experiments',
        Icon: IconFlask,
        iconColor: 'text-[var(--color-brand-yellow)]',
    },
    surveys: {
        label: 'Surveys',
        docsHref: 'https://posthog.com/docs/surveys',
        Icon: IconMessage,
        iconColor: 'text-[var(--color-brand-red)]',
    },
    error_tracking: {
        label: 'Error tracking',
        docsHref: 'https://posthog.com/docs/error-tracking',
        Icon: IconWarning,
        iconColor: 'text-[var(--color-brand-red)]',
    },
    data_warehouse: {
        label: 'Data warehouse',
        docsHref: 'https://posthog.com/docs/data-warehouse',
        Icon: IconDatabase,
        iconColor: 'text-secondary',
    },
    llm_analytics: {
        label: 'LLM analytics',
        docsHref: 'https://posthog.com/docs/ai-engineering/llm-analytics',
        Icon: IconLlmAnalytics,
        iconColor: 'text-[var(--color-brand-blue)]',
    },
    web_analytics: {
        label: 'Web analytics',
        docsHref: 'https://posthog.com/docs/web-analytics',
        Icon: IconPieChart,
        iconColor: 'text-[var(--color-brand-blue)]',
    },
}

const FALLBACK_META: ProductMeta = {
    label: '',
    docsHref: 'https://posthog.com/docs',
    Icon: IconDashboard,
    iconColor: 'text-secondary',
}

export function ProductsInUseCard(): JSX.Element | null {
    const { productsInUse } = useValues(welcomeDialogLogic)
    const { trackCardClick } = useActions(welcomeDialogLogic)

    if (productsInUse.length === 0) {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="p-6">
            <h2 className="text-lg font-semibold mb-1">Products your team uses</h2>
            <p className="text-xs text-muted mb-3 m-0">Click to read the docs.</p>
            <div className="flex flex-wrap gap-2">
                {productsInUse.map((productKey) => {
                    const meta = PRODUCT_META[productKey] ?? {
                        ...FALLBACK_META,
                        label: productKey.replace(/_/g, ' '),
                    }
                    return (
                        <Link
                            key={productKey}
                            to={meta.docsHref}
                            target="_blank"
                            subtle
                            onClick={() => trackCardClick('products', meta.docsHref)}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-border bg-bg-light hover:bg-accent-highlight-secondary text-sm"
                        >
                            <meta.Icon className={`text-base ${meta.iconColor}`} />
                            <span className="font-medium">{meta.label}</span>
                        </Link>
                    )
                })}
            </div>
        </LemonCard>
    )
}
