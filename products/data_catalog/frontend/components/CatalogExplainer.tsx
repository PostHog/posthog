import { useActions, useValues } from 'kea'

import * as stampApprovedPng from '@posthog/brand/hoggies/png/stamp-approved'
import { IconBook, IconX } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import { catalogExplainerLogic } from '../catalogExplainerLogic'

const EXPLAINER_PANEL_KEY = 'how-it-works'

const HedgehogStampApproved = pngHoggie(stampApprovedPng)

const STEPS = [
    'You or an agent proposes a metric with a name, a description, and a definition.',
    'Someone on your team reviews the definition and approves it.',
    'PostHog AI and agents on the PostHog MCP compute the metric from the approved definition.',
]

export function CatalogExplainer(): JSX.Element | null {
    const { explainerOpen, explainerDismissed } = useValues(catalogExplainerLogic)
    const { setExplainerOpen, dismissExplainer } = useActions(catalogExplainerLogic)

    if (explainerDismissed) {
        return null
    }

    return (
        // The data catalog's product color, swapped for its dark variant in dark mode.
        <LemonCollapse
            className="[--catalog-accent:var(--color-product-data-catalog-light)] dark:[--catalog-accent:var(--color-product-data-catalog-dark)] border-[color-mix(in_srgb,var(--catalog-accent)_35%,transparent)]"
            activeKey={explainerOpen ? EXPLAINER_PANEL_KEY : null}
            onChange={(activeKey) => setExplainerOpen(activeKey === EXPLAINER_PANEL_KEY)}
            panels={[
                {
                    key: EXPLAINER_PANEL_KEY,
                    header: {
                        children: (
                            <span className="flex items-center gap-2">
                                <IconBook className="size-4 text-[var(--catalog-accent)]" />
                                How the data catalog works
                            </span>
                        ),
                        sideAction: {
                            icon: <IconX />,
                            tooltip: "Don't show this again",
                            'aria-label': "Don't show this again",
                            onClick: dismissExplainer,
                            // pinned: data-attr values feed autocapture dashboards
                            'data-attr': 'data-catalog-explainer-dismiss',
                        },
                    },
                    dataAttr: 'data-catalog-explainer',
                    bodyClassName: 'bg-[color-mix(in_srgb,var(--catalog-accent)_6%,var(--color-bg-surface-primary))]',
                    content: (
                        <div className="flex items-center gap-4">
                            <div className="flex flex-col gap-2 text-sm flex-1 min-w-0">
                                <ol className="flex flex-wrap gap-x-6 gap-y-2 list-none p-0 m-0">
                                    {STEPS.map((step, index) => (
                                        <li key={step} className="flex gap-2 flex-1 min-w-48">
                                            <span className="shrink-0 size-5 rounded-full bg-[var(--catalog-accent)] text-white flex items-center justify-center text-xs font-semibold">
                                                {index + 1}
                                            </span>
                                            <span>{step}</span>
                                        </li>
                                    ))}
                                </ol>
                                <div className="text-secondary">
                                    Agents can also use proposed and drifted metrics. Their answers then include a
                                    warning.
                                </div>
                            </div>
                            <HedgehogStampApproved className="hidden @3xl:block size-20 shrink-0" />
                        </div>
                    ),
                },
            ]}
        />
    )
}
