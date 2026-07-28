import { useActions } from 'kea'

import { IconBook, IconGear } from '@posthog/icons'

import { TerminalCard } from 'lib/components/CommandBlock/TerminalCard'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
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

    // Mode-specific text overrides the base; missing fields fall back to it.
    const text: ProductEmptyStateText = { ...config.text['needs-setup'], ...config.text[mode] }

    // Wizard commands only work against cloud; self-hosted falls back to the manual path.
    const showWizard = !!config.wizard && isCloudOrDev

    const manualUrl = config.manualSetupUrl ?? config.docsUrl
    const Hedgehog = config.hedgehog
    const Preview = config.Preview

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
            <div className="mx-auto flex w-full min-w-0 max-w-[36rem] flex-col justify-center gap-4 px-6">
                <div className="flex flex-col items-start gap-3">
                    {Hedgehog ? <Hedgehog className="w-32 shrink-0" /> : null}
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
                    <TerminalCard command={wizardCommand} copyLabel={`${config.productName} wizard command`} />
                ) : config.primaryAction ? (
                    <LemonButton
                        type="primary"
                        to={config.primaryAction.to}
                        onClick={config.primaryAction.onClick}
                        className="self-start"
                    >
                        {config.primaryAction.label}
                    </LemonButton>
                ) : manualUrl ? (
                    <LemonButton type="primary" to={manualUrl} targetBlank className="self-start">
                        Set up {config.productName}
                    </LemonButton>
                ) : null}

                {config.statusIndicator ? <div className="text-xs">{config.statusIndicator}</div> : null}

                <div className="flex items-center gap-4">
                    {showWizard && manualUrl ? (
                        <LemonButton type="secondary" icon={<IconGear />} to={manualUrl} targetBlank>
                            Configure manually
                        </LemonButton>
                    ) : null}
                    {config.docsUrl ? (
                        <LemonButton size="xsmall" type="tertiary" icon={<IconBook />} to={config.docsUrl} targetBlank>
                            Read the docs
                        </LemonButton>
                    ) : null}
                    <LemonButton size="xsmall" type="tertiary" onClick={skipEmptyState}>
                        Skip for now
                    </LemonButton>
                </div>
            </div>

            <div
                className="hidden min-w-0 flex-col justify-center gap-3 p-10 md:flex rounded-md border border-primary"
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
