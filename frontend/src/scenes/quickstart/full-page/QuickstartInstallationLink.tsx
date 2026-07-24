import { IconRocket } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { captureQuickstartAction } from '../shared/captureQuickstartAction'

export function QuickstartInstallationLink(): JSX.Element {
    return (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconRocket />}
            to={urls.onboarding({
                productKey: ProductKey.PRODUCT_ANALYTICS,
                stepKey: OnboardingStepKey.INSTALL,
            })}
            onClick={() => captureQuickstartAction('return_to_installation')}
            data-attr="quickstart-return-to-installation"
        >
            Run setup wizard
        </LemonButton>
    )
}
