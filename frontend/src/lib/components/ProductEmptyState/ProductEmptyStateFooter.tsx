import { IconBook, IconGear } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { ProductEmptyStateConfig } from './types'

export function ProductEmptyStateFooter({
    config,
    manualSetupUrl,
    showManualSetup,
    onManualSetup,
    onDocs,
    onSkip,
}: {
    config: ProductEmptyStateConfig
    manualSetupUrl: string | undefined
    showManualSetup: boolean
    onManualSetup: () => void
    onDocs: () => void
    onSkip: () => void
}): JSX.Element {
    const links = (
        <>
            {showManualSetup && manualSetupUrl ? (
                <LemonButton
                    type="secondary"
                    icon={<IconGear />}
                    to={manualSetupUrl}
                    targetBlank
                    onClick={onManualSetup}
                    data-attr="product-empty-state-manual-setup"
                >
                    Configure manually
                </LemonButton>
            ) : null}
            {config.docsUrl ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconBook />}
                    to={config.docsUrl}
                    targetBlank
                    onClick={onDocs}
                    data-attr="product-empty-state-docs"
                >
                    Read the docs
                </LemonButton>
            ) : null}
            {config.skippable !== false ? (
                <LemonButton size="xsmall" type="tertiary" onClick={onSkip} data-attr="product-empty-state-skip">
                    Skip for now
                </LemonButton>
            ) : null}
        </>
    )

    return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {config.FooterActions ? <config.FooterActions>{links}</config.FooterActions> : links}
        </div>
    )
}
