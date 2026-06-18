import { useActions } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MailHog } from 'lib/components/hedgehogs'

import { onboardingExitLogic } from './onboardingExitLogic'

export function OnboardingExitAction(): JSX.Element {
    const { openExitModal } = useActions(onboardingExitLogic)

    // Modal is co-mounted in ProductSelection.tsx (one mount per onboarding entry point) so
    // multiple OnboardingExitAction renders in a single tree share the same kea state without
    // spawning competing LemonModal instances.
    return (
        <div className="mt-8 mx-auto max-w-md w-full">
            <div className="flex items-center gap-3 p-3 rounded-lg border border-primary bg-surface-primary">
                <MailHog className="w-16 h-11 object-contain shrink-0" />
                <div className="flex-1 text-left min-w-0">
                    <p className="m-0 text-sm font-semibold">Not the one setting this up?</p>
                    <p className="m-0 text-xs text-muted">Hand setup over to a teammate to finish.</p>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={openExitModal}
                    sideIcon={<IconArrowRight />}
                    data-attr="onboarding-exit-link"
                >
                    Hand off setup
                </LemonButton>
            </div>
        </div>
    )
}
