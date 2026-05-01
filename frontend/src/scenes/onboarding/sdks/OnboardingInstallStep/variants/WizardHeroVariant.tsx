import { LemonBanner } from '@posthog/lemon-ui'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../../../OnboardingStep'
import { AdblockWarning, RealtimeCheckIndicator } from '../../RealtimeCheckIndicator'
import { SDKGrid } from '../SDKGrid'
import { VariantProps } from '../types'
import { WizardCommandBlock } from '../WizardCommandBlock'

/**
 * ONBOARDING_WIZARD_PROMINENCE = "wizard-hero"
 * Wizard banner prominently above the SDK grid — both visible at once, wizard given
 * visual primacy via a LemonBanner + divider ("Or, set up manually").
 */
export function WizardHeroVariant({
    sdkGridProps,
    adblockResult,
    installationComplete,
    listeningForName,
    teamPropertyToVerify,
    header,
}: VariantProps): JSX.Element {
    return (
        <OnboardingStep
            title="Install"
            stepKey={OnboardingStepKey.INSTALL}
            continueDisabledReason={!installationComplete ? 'Installation is not complete' : undefined}
            showSkip={!installationComplete}
            actions={
                <div className="pr-2">
                    <RealtimeCheckIndicator
                        teamPropertyToVerify={teamPropertyToVerify}
                        listeningForName={listeningForName}
                    />
                </div>
            }
        >
            {header}
            {!installationComplete && <AdblockWarning adblockResult={adblockResult} />}
            <div className="mt-6 space-y-6">
                <LemonBanner type="info" hideIcon>
                    <div className="p-2">
                        <h3 className="text-lg font-bold mb-1">Install PostHog with one command</h3>
                        <p className="text-sm mb-4">
                            The AI wizard auto-detects your framework and sets everything up. Just paste this into your
                            terminal.
                        </p>
                        <WizardCommandBlock />
                    </div>
                </LemonBanner>

                <div className="flex items-center gap-3">
                    <div className="flex-1 border-t border-border" />
                    <span className="text-muted font-semibold text-xs uppercase">Or, set up manually</span>
                    <div className="flex-1 border-t border-border" />
                </div>

                <SDKGrid {...sdkGridProps} />
            </div>
        </OnboardingStep>
    )
}
