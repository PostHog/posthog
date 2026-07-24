import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { getProductIcon } from 'scenes/onboarding/shared/utils'
import { activeCloudRunLogic } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'
import {
    InstallationProgressView,
    useLocalWizardRunActive,
} from 'scenes/onboarding/shared/wizard-sync/InstallationProgressView'
import { WizardCloudRunBlock } from 'scenes/onboarding/shared/wizard-sync/WizardCloudRunBlock'
import { WizardCommandBlock } from 'scenes/onboarding/shared/wizard-sync/WizardCommandBlock'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { quickstartLogic } from '../quickstartLogic'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'
import { QuickstartWizardProgress } from '../shared/QuickstartWizardProgress'
import { INSTALL_MODE_CARDS, QuickstartInstallMode } from './installModeCards'
import { QuickstartRunStatus } from './QuickstartRunStatus'

// The install decision as a master-detail layout: intro and stacked radio cards on the
// left, the chosen mode's expanded content on the right. Same rules as onboarding's
// WizardInstallOptions: a cloud run pins the view to its progress; a failed run falls
// back to the command.
export function QuickstartInstallSwitcher({ intro }: { intro: React.ReactNode }): JSX.Element {
    const cloudRunEnabled = useFeatureFlag('ONBOARDING_WIZARD_CLOUD_RUN', 'test')
    const { isCloudOrDev } = useValues(preflightLogic)
    const { activeCloudRun } = useValues(activeCloudRunLogic)
    const { clearActiveCloudRun } = useActions(activeCloudRunLogic)
    const { featuredProducts } = useValues(quickstartLogic)
    const { openToolSetupModal } = useActions(quickstartLogic)

    const isLocalRunActive = useLocalWizardRunActive()
    const offerCloud = cloudRunEnabled && isCloudOrDev
    const [mode, setMode] = useState<QuickstartInstallMode>(offerCloud ? 'cloud' : 'local')
    const cloudRunPinned = !!activeCloudRun
    // Once an installation is triggered, the choice is locked until it errors out (the
    // failed-run fallbacks clear the run state, which unlocks the cards again)
    const installationTriggered = cloudRunPinned || isLocalRunActive
    const effectiveMode: QuickstartInstallMode = cloudRunPinned ? 'cloud' : isLocalRunActive ? 'local' : mode
    const runItYourself = (): void => {
        clearActiveCloudRun()
        setMode('local')
    }

    const cards = INSTALL_MODE_CARDS.filter((card) => card.value !== 'cloud' || offerCloud)

    return (
        <div className="grid grid-cols-1 @3xl/main-content:grid-cols-2 gap-6">
            <div className="flex flex-col gap-4">
                {intro}
                <div className="grid grid-cols-1 @2xl/main-content:grid-cols-3 gap-2" role="radiogroup">
                    {cards.map((card) => {
                        const selected = effectiveMode === card.value
                        const disabled = installationTriggered && card.value !== effectiveMode
                        return (
                            <button
                                key={card.value}
                                type="button"
                                role="radio"
                                aria-checked={selected}
                                disabled={disabled}
                                title={disabled ? 'Installation in progress.' : undefined}
                                className={cn(
                                    'text-left rounded border p-3 bg-bg-light transition-colors flex flex-col justify-start gap-1',
                                    selected ? 'border-accent' : 'hover:border-secondary',
                                    disabled && 'opacity-50 cursor-not-allowed'
                                )}
                                onClick={() => {
                                    if (card.value !== effectiveMode) {
                                        captureQuickstartAction('install_mode_selected', undefined, {
                                            mode: card.value,
                                        })
                                    }
                                    setMode(card.value)
                                }}
                                data-attr={`quickstart-wizard-mode-${card.value}`}
                            >
                                <span className="text-lg">{card.icon}</span>
                                <div className="font-semibold text-sm min-h-10">{card.title}</div>
                                <div className="text-secondary text-xs">{card.description}</div>
                            </button>
                        )
                    })}
                </div>
            </div>
            <div className="rounded border bg-surface-primary p-4 flex flex-col gap-4 h-full">
                {effectiveMode === 'cloud' ? (
                    cloudRunPinned ? (
                        <QuickstartWizardProgress
                            fallback={<WizardCloudRunBlock hideHog align="start" onRetryLocally={runItYourself} />}
                        >
                            {(progress) => <QuickstartRunStatus progress={progress} onRetryLocally={runItYourself} />}
                        </QuickstartWizardProgress>
                    ) : (
                        <WizardCloudRunBlock hideHog align="start" onRetryLocally={runItYourself} />
                    )
                ) : effectiveMode === 'local' ? (
                    isLocalRunActive ? (
                        <InstallationProgressView mode="local" />
                    ) : (
                        <WizardCommandBlock hideHog align="start" />
                    )
                ) : (
                    <div className="flex flex-col gap-2">
                        <p className="text-secondary text-sm mb-0">
                            Pick a tool to open its install guide with instructions for every SDK and framework.
                        </p>
                        <div className="flex flex-wrap gap-2">
                            {featuredProducts.map((product) => (
                                <LemonButton
                                    key={product.key}
                                    type="secondary"
                                    size="small"
                                    icon={getProductIcon(product.icon, { iconColor: product.iconColor })}
                                    onClick={() => {
                                        captureQuickstartAction('set_up_product', product.key, {
                                            source: 'focused_install',
                                        })
                                        openToolSetupModal(product.key)
                                    }}
                                    data-attr={`quickstart-focused-setup-${product.key}`}
                                >
                                    {product.name}
                                </LemonButton>
                            ))}
                        </div>
                        <Link
                            to="https://posthog.com/docs/libraries"
                            target="_blank"
                            className="text-sm"
                            onClick={() =>
                                captureQuickstartAction('open_sdk_docs', undefined, { source: 'focused_install' })
                            }
                        >
                            Browse all SDK docs
                        </Link>
                    </div>
                )}
            </div>
        </div>
    )
}
