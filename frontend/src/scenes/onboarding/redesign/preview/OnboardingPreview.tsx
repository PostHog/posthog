import { useValues } from 'kea'

import { onboardingLogic } from '../onboardingLogic'
import { buildPreviewConfig } from './presets'
import { PreviewChrome } from './PreviewChrome'

export function OnboardingPreview(): JSX.Element {
    const { currentStepKey, organizationName, selectedProducts, name, archetypeId } = useValues(onboardingLogic)
    const config = buildPreviewConfig(currentStepKey, {
        orgName: organizationName,
        products: selectedProducts,
        userName: name,
        archetypeId,
    })

    return <PreviewChrome config={config} />
}
