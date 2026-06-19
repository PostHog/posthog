import { useValues } from 'kea'

import { onboardingLogic } from '../onboardingLogic'
import { buildPreviewConfig } from './presets'
import { PreviewChrome } from './PreviewChrome'

/** Live preview shown in the onboarding right pane. Derives its config from the current step + selections. */
export function OnboardingPreview(): JSX.Element {
    const { currentStepKey, organizationName, selectedProducts } = useValues(onboardingLogic)
    const config = buildPreviewConfig(currentStepKey, { orgName: organizationName, products: selectedProducts })

    return (
        <div className="flex h-full w-full flex-col items-center gap-3">
            <div className="flex min-h-0 w-full max-w-[760px] flex-1">
                <PreviewChrome config={config} />
            </div>
            <p className="text-muted shrink-0 text-center text-xs">A preview of your PostHog, updating as you go.</p>
        </div>
    )
}
