import { useActions } from 'kea'
import posthog from 'posthog-js'

import { IconBook, IconGear } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TerminalCard } from 'lib/components/CommandBlock/TerminalCard'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'

import { productSetupStatusLogic } from './productSetupStatusLogic'
import type { ProductEmptyStateConfig, ProductEmptyStateMode, ProductEmptyStateText } from './types'

export interface ProductEmptyStateProps {
    config: ProductEmptyStateConfig
    mode: ProductEmptyStateMode
}

const ACCENT_TEXT = 'text-[var(--empty-state-accent)] dark:text-[var(--empty-state-accent-dark)]'

/**
 * The product setup empty state: pitch + install command on the left, an animated
 * preview of the product filled with example data on the right. Shown before
 * a product has been set up — gate it with `ProductEmptyStateGate` (or declare
 * `emptyState` on the scene's `SceneExport` and the app shell gates for you).
 */
export function ProductEmptyState({ config, mode }: ProductEmptyStateProps): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand(config.wizard?.slug, {
        pinProjectId: config.wizard?.pinProjectId,
    })
    const { skipEmptyState } = useActions(productSetupStatusLogic({ productKey: config.productKey }))

    const captureClick = (action: string): void => {
        posthog.capture(`product empty state ${action}`, { product_key: config.productKey, mode })
    }

    // Mode-specific text overrides the base; missing fields fall back to it.
    const text: ProductEmptyStateText = { ...config.text['needs-setup'], ...config.text[mode] }

    // Wizard commands only work against cloud; self-hosted falls back to the manual path.
    const showWizard = !!config.wizard && isCloudOrDev

    const manualUrl = config.manualSetupUrl ?? config.docsUrl
    const Hedgehog = config.hedgehog
    const Preview = config.Preview
    const hedgehogBeside = config.hedgehogPlacement === 'beside'

    const { primaryAction } = config
    const primaryActionButton = primaryAction ? (
        <LemonButton
            type="primary"
            to={primaryAction.to}
            onClick={() => {
                captureClick('primary action clicked')
                primaryAction.onClick?.()
            }}
            className="self-start"
            data-attr={primaryAction.dataAttr ?? 'product-empty-state-primary-action'}
        >
            {primaryAction.label}
        </LemonButton>
    ) : null
    const guardedPrimaryAction =
        primaryActionButton && primaryAction?.accessControl ? (
            <AccessControlAction
                resourceType={primaryAction.accessControl.resourceType}
                minAccessLevel={primaryAction.accessControl.minAccessLevel}
            >
                {primaryActionButton}
            </AccessControlAction>
        ) : (
            primaryActionButton
        )

    return (
        <div
            // Fill the scene: viewport minus the app chrome and the product header above us.
            className="grid w-full flex-1 grid-cols-1 items-stretch gap-10 md:grid-cols-[minmax(0,1fr)_40%] min-h-[calc(100vh-var(--breadcrumbs-height-full,0px)-var(--scene-padding,1rem)-4rem)]"
            style={
                {
                    '--empty-state-accent': config.accentColor,
                    '--empty-state-accent-dark': config.accentColorDark ?? config.accentColor,
                } as React.CSSProperties
            }
        >
            <div
                className={cn(
                    'mx-auto flex w-full min-w-0 justify-center gap-8 px-6',
                    hedgehogBeside ? 'max-w-[56rem] items-center' : 'max-w-[36rem]'
                )}
            >
                {Hedgehog && hedgehogBeside ? <Hedgehog className="hidden w-72 shrink-0 xl:block" /> : null}
                <div className="flex min-w-0 max-w-[36rem] flex-col justify-center gap-4">
                    <div className="flex flex-col items-start gap-3">
                        {Hedgehog && !hedgehogBeside ? <Hedgehog className="w-32 shrink-0" /> : null}
                        <div className="inline-flex items-center gap-2.5 text-4xl font-bold [&_svg]:text-[2.25rem]">
                            <span className={ACCENT_TEXT}>{config.icon}</span>
                            <span>{config.productName}</span>
                        </div>
                    </div>
                    <div className="flex flex-col gap-1">
                        <h2 className="text-xl font-semibold m-0">{text.headline}</h2>
                        <p className="text-secondary text-sm m-0">{text.lead}</p>
                    </div>

                    {text.hint ? <div className="text-xs text-tertiary mt-2">{text.hint}</div> : null}

                    {showWizard ? (
                        <>
                            <TerminalCard
                                command={wizardCommand}
                                copyLabel={`${config.productName} wizard command`}
                                onCopy={() => captureClick('wizard command copied')}
                            />
                            {guardedPrimaryAction ? (
                                <>
                                    <div className="flex items-center gap-3">
                                        <div className="h-px flex-1 bg-border-primary" />
                                        <span className="text-xs text-tertiary uppercase tracking-wide">or</span>
                                        <div className="h-px flex-1 bg-border-primary" />
                                    </div>
                                    {guardedPrimaryAction}
                                </>
                            ) : null}
                        </>
                    ) : config.PrimaryAction ? (
                        <config.PrimaryAction />
                    ) : guardedPrimaryAction ? (
                        guardedPrimaryAction
                    ) : manualUrl ? (
                        <LemonButton
                            type="primary"
                            to={manualUrl}
                            targetBlank
                            className="self-start"
                            onClick={() => captureClick('manual setup clicked')}
                            data-attr="product-empty-state-manual-setup"
                        >
                            Set up {config.productName}
                        </LemonButton>
                    ) : null}

                    {config.statusIndicator ? <div className="text-xs">{config.statusIndicator}</div> : null}

                    <div className="flex items-center gap-4">
                        {showWizard && !primaryActionButton && manualUrl ? (
                            <LemonButton
                                type="secondary"
                                icon={<IconGear />}
                                to={manualUrl}
                                targetBlank
                                onClick={() => captureClick('manual setup clicked')}
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
                                onClick={() => captureClick('docs clicked')}
                                data-attr="product-empty-state-docs"
                            >
                                Read the docs
                            </LemonButton>
                        ) : null}
                        {config.skippable !== false ? (
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={skipEmptyState}
                                data-attr="product-empty-state-skip"
                            >
                                Skip for now
                            </LemonButton>
                        ) : null}
                    </div>
                </div>
            </div>

            <div
                // Previews read `--empty-state-accent` only, so in dark mode point that at the dark
                // token here rather than asking every preview to branch on the theme itself.
                className="hidden min-w-0 flex-col justify-center gap-3 p-10 md:flex rounded-md border border-primary dark:[--empty-state-accent:var(--empty-state-accent-dark)]"
                style={{
                    backgroundImage:
                        'linear-gradient(135deg, color-mix(in oklab, var(--empty-state-accent) 16%, transparent) 0%, color-mix(in oklab, var(--empty-state-accent) 5%, transparent) 45%, transparent 80%)',
                }}
            >
                <div className="flex items-center gap-2 text-xs font-semibold text-secondary">
                    <span
                        className="size-2 rounded-full bg-[var(--empty-state-accent)] dark:bg-[var(--empty-state-accent-dark)] animate-pulse motion-reduce:animate-none"
                        aria-hidden="true"
                    />
                    {config.previewLabel}
                </div>
                <Preview mode={mode} />
            </div>
        </div>
    )
}
