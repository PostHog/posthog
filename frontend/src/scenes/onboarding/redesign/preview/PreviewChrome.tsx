import clsx from 'clsx'

import { IconLogomark, IconPlus } from '@posthog/icons'

import { availableOnboardingProducts, getProductIcon } from '../../shared/utils'
import { PreviewPageView } from './pages'
import { type PreviewConfig } from './types'

/** The shared preview frame: org header + product sidebar + a top bar, with the swappable page in the center. */
export function PreviewChrome({ config }: { config: PreviewConfig }): JSX.Element {
    const products = availableOnboardingProducts as Record<string, { name: string } | undefined>
    const navProducts = config.sidebar.products
    const activeKey = config.sidebar.activeProductKey ?? navProducts[0] ?? null
    const activeName = activeKey ? products[activeKey]?.name : null

    return (
        <div className="flex h-full w-full overflow-hidden rounded-xl border border-primary bg-primary shadow-lg">
            {/* Sidebar */}
            <div className="flex w-32 shrink-0 flex-col gap-0.5 border-r border-primary bg-surface-secondary p-2">
                <div className="mb-2 flex items-center gap-1.5 px-1">
                    <IconLogomark className="text-base" />
                    <span className="truncate text-xs font-bold text-default">{config.org.name}</span>
                </div>
                {navProducts.map((key) => {
                    const product = products[key]
                    if (!product) {
                        return null
                    }
                    const active = key === activeKey
                    return (
                        <div
                            key={key}
                            className={clsx(
                                'flex items-center gap-2 rounded px-1.5 py-1 text-[11px] font-medium',
                                active ? 'bg-surface-primary text-default' : 'text-secondary'
                            )}
                        >
                            <span className="flex h-3.5 w-3.5 items-center justify-center text-[11px]">
                                {getProductIcon(null, { productType: key })}
                            </span>
                            <span className="truncate">{product.name}</span>
                        </div>
                    )
                })}
                <div className="text-muted mt-auto flex items-center gap-1.5 px-1.5 pt-1 text-[11px]">
                    <IconPlus className="text-xs" /> Add products
                </div>
            </div>
            {/* Main */}
            <div className="flex min-w-0 flex-1 flex-col">
                <div className="flex h-9 shrink-0 items-center gap-2 border-b border-primary px-3">
                    <span className="truncate text-xs font-bold text-default">{activeName ?? 'Home'}</span>
                    <span className="ml-auto h-4 w-4 shrink-0 rounded-full bg-accent" />
                </div>
                <div className="min-h-0 flex-1 overflow-hidden p-3">
                    <PreviewPageView page={config.page} />
                </div>
            </div>
        </div>
    )
}
