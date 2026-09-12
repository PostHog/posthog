import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconBook, IconGear } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TerminalCard } from 'lib/components/CommandBlock/TerminalCard'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'
import { useWizardCommand } from 'scenes/onboarding/shared/useWizardCommand'
import { teamLogic } from 'scenes/teamLogic'

import { productSetupStatusLogic } from './productSetupStatusLogic'
import type {
    ProductEmptyStateConfig,
    ProductEmptyStateMode,
    ProductEmptyStatePrimaryAction,
    ProductEmptyStateText,
    ProductEmptyStateWizard,
} from './types'

export interface ProductEmptyStateProps {
    config: ProductEmptyStateConfig
    mode: ProductEmptyStateMode
    preview?: boolean
}

const ACCENT_TEXT = 'text-[var(--empty-state-accent)] dark:text-[var(--empty-state-accent-dark)]'

/** A single action covers every mode; a mode-keyed one applies only to the modes it names. */
function resolvePrimaryAction(
    primaryAction: ProductEmptyStateConfig['primaryAction'],
    mode: ProductEmptyStateMode
): ProductEmptyStatePrimaryAction | undefined {
    if (!primaryAction) {
        return undefined
    }
    return 'label' in primaryAction ? primaryAction : primaryAction[mode]
}

/** A single wizard covers every mode; a mode-keyed one applies only to the modes it names. */
function resolveWizard(
    wizard: ProductEmptyStateConfig['wizard'],
    mode: ProductEmptyStateMode
): ProductEmptyStateWizard | undefined {
    if (!wizard) {
        return undefined
    }
    return 'slug' in wizard ? wizard : wizard[mode]
}

/**
 * The product setup empty state: pitch + install command on the left, an animated
 * preview of the product filled with example data on the right. Shown before
 * a product has been set up — gate it with `ProductEmptyStateGate` (or declare
 * `emptyState` on the scene's `SceneExport` and the app shell gates for you).
 */
export function ProductEmptyState({ config, mode, preview = false }: ProductEmptyStateProps): JSX.Element {
    const wizard = resolveWizard(config.wizard, mode)
    const { wizardCommand, isCloudOrDev } = useWizardCommand(wizard?.slug, {
        pinProjectId: wizard?.pinProjectId,
    })
    const { skipEmptyState, reportSetupShown, reportSetupInteraction } = useActions(
        productSetupStatusLogic({ productKey: config.productKey })
    )
    const { currentTeam } = useValues(teamLogic)
    const projectUuid = currentTeam?.uuid

    useEffect(() => {
        reportSetupShown(mode, preview)
    }, [mode, preview, projectUuid, reportSetupShown])

    const captureClick = (action: string): void => {
        const route =
            action === 'wizard command copied' ? 'wizard' : action === 'manual setup clicked' ? 'manual' : null
        reportSetupInteraction(action, mode, route, preview)
    }

    // Mode-specific text overrides the base; missing fields fall back to it.
    const text: ProductEmptyStateText = { ...config.text['needs-setup'], ...config.text[mode] }

    // Wizard commands only work against cloud; self-hosted falls back to the manual path.
    const showWizard = !!wizard && isCloudOrDev

    const manualUrl = config.manualSetupUrl ?? config.docsUrl
    const Hedgehog = config.hedgehog
    const Preview = config.Preview
    const hedgehogBeside = config.hedgehogPlacement === 'beside'

    const primaryAction = resolvePrimaryAction(config.primaryAction, mode)
    // Safe to call unconditionally: it answers with a loading reason until the team lands, and
    // the widest scope is a no-op for actions that declare no restriction.
    const restrictionReason = useRestrictedArea({
        scope: primaryAction?.restriction?.scope ?? RestrictionScope.Project,
        minimumAccessLevel: primaryAction?.restriction?.minimumAccessLevel ?? TeamMembershipLevel.Member,
    })
    const primaryActionRestriction = primaryAction?.restriction ? restrictionReason : null
    const primaryActionButton = primaryAction ? (
        <LemonButton
            type="primary"
            to={primaryAction.to}
            onClick={() => {
                captureClick('primary action clicked')
                primaryAction.onClick?.()
            }}
            className="self-start"
            disabledReason={primaryActionRestriction}
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

    // The hint, the wizard card and the primary action are one block: the hint introduces
    // whatever sits under it, so a mode without an action drops its lead-in too. Offering
    // the manual setup link as the fallback CTA only fits a product still needing setup.
    const callToAction = showWizard ? (
        <>
            <TerminalCard
                command={wizardCommand}
                copyLabel={`${config.productName} wizard command`}
                onCopy={() => captureClick('wizard command copied')}
            />
            {config.PrimaryAction || guardedPrimaryAction ? (
                <>
                    <div className="flex items-center gap-3">
                        <div className="h-px flex-1 bg-border-primary" />
                        <span className="text-xs text-tertiary uppercase tracking-wide">or</span>
                        <div className="h-px flex-1 bg-border-primary" />
                    </div>
                    {config.PrimaryAction ? <config.PrimaryAction /> : guardedPrimaryAction}
                </>
            ) : null}
        </>
    ) : config.PrimaryAction ? (
        <config.PrimaryAction />
    ) : guardedPrimaryAction ? (
        guardedPrimaryAction
    ) : manualUrl && mode === 'needs-setup' ? (
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
    ) : null

    return (
        // Breakpoints key off our own width, not the viewport: the sidebar, the side panel, and
        // the scene padding all eat into it, so a viewport breakpoint fires long after the copy
        // has already been squeezed. Two containers because the two decisions read different
        // widths - the preview watches the whole surface, the hedgehog watches the copy column.
        <div
            // Frozen selector used by Playwright to detect the setup screen.
            data-attr="product-empty-state"
            className="@container/product-empty-state flex w-full flex-1"
            style={
                {
                    '--empty-state-accent': config.accentColor,
                    '--empty-state-accent-dark': config.accentColorDark ?? config.accentColor,
                } as React.CSSProperties
            }
        >
            <div
                // Fill the scene: viewport minus the app chrome and the product header above us.
                // Side by side needs 64rem for both halves to hold their content; below that the
                // preview stacks under the copy, so a narrow scene keeps the pitch and the
                // preview rather than squeezing both into columns too narrow to read.
                className="grid w-full flex-1 grid-cols-1 items-stretch gap-10 @min-[64rem]/product-empty-state:grid-cols-[minmax(0,1fr)_40%] min-h-[calc(100vh-var(--breadcrumbs-height-full,0px)-var(--scene-padding,1rem)-4rem)]"
            >
                <div
                    className={cn(
                        '@container/product-empty-state-copy mx-auto flex w-full min-w-0 justify-center gap-8 px-6',
                        // Widening the column to seat the illustration beside the copy is only
                        // worth it once the preview is up in its own column, so it stays capped
                        // while the two are stacked.
                        hedgehogBeside
                            ? 'max-w-[36rem] items-center @min-[64rem]/product-empty-state:max-w-[56rem]'
                            : 'max-w-[36rem]'
                    )}
                >
                    {Hedgehog && hedgehogBeside ? (
                        // At this width the illustration still leaves the copy 32rem, about what
                        // an `above` empty state gives it. Below it the column drops the wide
                        // illustration and falls back to the small one above the product name.
                        <Hedgehog className="hidden w-72 shrink-0 @min-[52rem]/product-empty-state-copy:block" />
                    ) : null}
                    <div className="flex min-w-0 max-w-[36rem] flex-col justify-center gap-4">
                        <div className="flex flex-col items-start gap-3">
                            {Hedgehog ? (
                                <Hedgehog
                                    className={cn(
                                        'shrink-0',
                                        // `beside` artwork is wide rather than square, so it needs
                                        // more width than an `above` hedgehog to stay legible here.
                                        hedgehogBeside ? 'w-48 @min-[52rem]/product-empty-state-copy:hidden' : 'w-32'
                                    )}
                                />
                            ) : null}
                            <div className="inline-flex items-center gap-2.5 text-4xl font-bold [&_svg]:text-[2.25rem]">
                                <span className={ACCENT_TEXT}>{config.icon}</span>
                                <span>{config.productName}</span>
                            </div>
                        </div>
                        <div className="flex flex-col gap-1">
                            <h2 className="text-xl font-semibold m-0">{text.headline}</h2>
                            <p className="text-secondary text-sm m-0">{text.lead}</p>
                        </div>

                        {text.hint && callToAction ? (
                            <div className="text-xs text-tertiary mt-2">{text.hint}</div>
                        ) : null}

                        {callToAction}

                        {config.SetupActions ? <config.SetupActions mode={mode} preview={preview} /> : null}

                        {config.statusIndicator ? <div className="text-xs">{config.statusIndicator}</div> : null}

                        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                            {showWizard && !primaryActionButton && !config.PrimaryAction && manualUrl ? (
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
                    // Tighter padding while stacked, where the width goes to the preview itself.
                    className="flex min-w-0 flex-col justify-center gap-3 p-6 @min-[64rem]/product-empty-state:p-10 rounded-md border border-primary dark:[--empty-state-accent:var(--empty-state-accent-dark)]"
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
        </div>
    )
}
