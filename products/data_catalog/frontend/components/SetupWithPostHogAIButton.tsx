import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { CatalogSetupSource, catalogSetupLogic } from '../catalogSetupLogic'

export function SetupWithPostHogAIButton({
    source,
    type = 'primary',
}: {
    source: CatalogSetupSource
    type?: LemonButtonProps['type']
}): JSX.Element {
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const { startSetupWithPostHogAI } = useActions(catalogSetupLogic)

    return (
        // `ignoreDismissal` keeps the consent popover reachable after a previous dismissal, so an
        // unapproved click always has a way to grant consent rather than doing nothing.
        <AIConsentPopoverWrapper onApprove={() => startSetupWithPostHogAI(source)} ignoreDismissal>
            <LemonButton
                type={type}
                icon={<IconSparkles />}
                sideIcon={null}
                // The wrapper does not swallow the click. Without this guard an unapproved click would
                // start setup here and again from `onApprove`.
                onClick={() => dataProcessingAccepted && startSetupWithPostHogAI(source)}
                // pinned: data-attr values feed autocapture dashboards
                data-attr={`data-catalog-setup-with-ai-${source}`}
            >
                Set up with PostHog AI
            </LemonButton>
        </AIConsentPopoverWrapper>
    )
}
