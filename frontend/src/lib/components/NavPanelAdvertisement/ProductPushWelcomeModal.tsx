import type { CSSProperties } from 'react'

import { IconBook } from '@posthog/icons'

import type { ProductEmptyStateConfig, ProductEmptyStateText } from 'lib/components/ProductEmptyState/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { ProductHogHero } from './navPanelAdShared'
import { getProductPushDisplay } from './navPanelProductPushDisplay'
import type { ProductPushWelcomeCloseSource } from './navPanelProductPushWelcomeLogic'
import type { PendingProductPushWelcome } from './navPanelProductPushWelcomeVisibility'

// Same treatment the setup screen gives the product icon, over accents this sets locally.
const ACCENT_TEXT = 'text-[var(--empty-state-accent)] dark:text-[var(--empty-state-accent-dark)]'

/**
 * `config` is the setup screen the scene would have shown if the product had no data. Taking the
 * pitch from there keeps one description of each product: the user who needs setup reads it on the
 * setup screen, and the user who already has data reads the same words here.
 */
export function ProductPushWelcomeModal({
    welcome,
    config,
    onClose,
}: {
    welcome: PendingProductPushWelcome
    config?: ProductEmptyStateConfig
    onClose: (source: ProductPushWelcomeCloseSource) => void
}): JSX.Element {
    const text = config?.text['needs-setup']
    const productName = config?.productName ?? welcome.label

    return (
        <LemonModal
            isOpen
            onClose={() => onClose('modal_close')}
            width={480}
            title={
                <span className="flex items-center gap-2" style={accentVariables(config)}>
                    {config ? <span className={`flex ${ACCENT_TEXT}`}>{config.icon}</span> : null}
                    <span>Welcome to {productName}</span>
                </span>
            }
            data-attr="product-push-welcome"
            footer={
                <div className="flex w-full items-center justify-between gap-2">
                    {config?.docsUrl ? (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconBook />}
                            to={config.docsUrl}
                            targetBlank
                            data-attr="product-push-welcome-docs"
                        >
                            Read the docs
                        </LemonButton>
                    ) : (
                        <div />
                    )}
                    <LemonButton
                        type="primary"
                        onClick={() => onClose('start_exploring')}
                        data-attr="product-push-welcome-close"
                    >
                        Start exploring
                    </LemonButton>
                </div>
            }
        >
            {config && text ? (
                <ProductIntro config={config} text={text} />
            ) : (
                // A product with no setup screen has only the card's own blurb to introduce it.
                <div className="overflow-hidden rounded border bg-surface-primary text-xs">
                    <ProductHogHero
                        hero={getProductPushDisplay(welcome.productKey)}
                        title={welcome.label}
                        text={welcome.text}
                    />
                </div>
            )}
        </LemonModal>
    )
}

function ProductIntro({ config, text }: { config: ProductEmptyStateConfig; text: ProductEmptyStateText }): JSX.Element {
    const Hedgehog = config.hedgehog
    return (
        <div className="flex items-start gap-4" style={accentVariables(config)}>
            {Hedgehog ? <Hedgehog className="w-24 shrink-0" /> : null}
            <div className="flex min-w-0 flex-col gap-1">
                <h3 className="m-0 text-base font-semibold">{text.headline}</h3>
                <p className="m-0 text-sm text-secondary">{text.lead}</p>
            </div>
        </div>
    )
}

function accentVariables(config?: ProductEmptyStateConfig): CSSProperties | undefined {
    return config
        ? ({
              '--empty-state-accent': config.accentColor,
              '--empty-state-accent-dark': config.accentColorDark ?? config.accentColor,
          } as CSSProperties)
        : undefined
}
