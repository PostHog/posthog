import { useState } from 'react'

import { LemonTabs } from '@posthog/lemon-ui'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../../../OnboardingStep'
import { AdblockWarning, RealtimeCheckIndicator } from '../../RealtimeCheckIndicator'
import { SDKGrid } from '../SDKGrid'
import { VariantProps } from '../types'
import { WizardCommandBlock } from '../WizardCommandBlock'

/**
 * ONBOARDING_WIZARD_PROMINENCE = "wizard-tab"
 * Wizard and SDK grid split across two top-level tabs ("AI wizard" / "Manual setup"),
 * wizard tab selected by default and tagged "Recommended".
 */
export function WizardTabVariant({
    sdkGridProps,
    adblockResult,
    installationComplete,
    listeningForName,
    teamPropertyToVerify,
    header,
}: VariantProps): JSX.Element {
    const [activeTab, setActiveTab] = useState<string>('wizard')

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
            <div className="mt-6">
                <LemonTabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    tabs={[
                        {
                            key: 'wizard',
                            label: (
                                <span className="flex items-center gap-1.5">
                                    AI wizard
                                    <span className="bg-success-highlight text-success text-[10px] font-bold px-1.5 py-0.5 rounded-sm uppercase">
                                        Recommended
                                    </span>
                                </span>
                            ),
                        },
                        {
                            key: 'manual',
                            label: 'Manual setup',
                        },
                    ]}
                />

                {activeTab === 'wizard' ? (
                    <div className="mt-4 space-y-6">
                        <div>
                            <h3 className="text-base font-semibold mb-2">Install PostHog automatically</h3>
                            <p className="text-sm text-muted mb-4">
                                Run this command in your project directory. The wizard will detect your framework,
                                install the SDK, and configure event capture.
                            </p>
                        </div>
                        <WizardCommandBlock />
                    </div>
                ) : (
                    <div className="mt-4">
                        <SDKGrid {...sdkGridProps} />
                    </div>
                )}
            </div>
        </OnboardingStep>
    )
}
