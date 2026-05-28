import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { ErrorTrackingIngestionPrompt } from 'products/error_tracking/frontend/components/SetupPrompt/SetupPrompt'

import type { WidgetAvailabilityConfig } from '../../widget_types/widgetAvailability'
import { WidgetCardContent } from '../WidgetCard/WidgetCardBody'
import { WidgetCardProductIntroduction } from '../WidgetCardProductIntroduction/WidgetCardProductIntroduction'

type WidgetAvailabilitySetupPromptProps = {
    availability: WidgetAvailabilityConfig
    className?: string
}

export function WidgetAvailabilitySetupPrompt({
    availability,
    className,
}: WidgetAvailabilitySetupPromptProps): JSX.Element {
    switch (availability.requirement) {
        // New requirements: add a case here — CONTRIBUTING.md
        case 'exception_autocapture':
            return (
                <WidgetCardContent className={className}>
                    <ErrorTrackingIngestionPrompt
                        className="border-none mb-0 mt-0 p-4"
                        IntroductionComponent={WidgetCardProductIntroduction}
                        actionElementClassName="flex flex-col items-center gap-4 @min-[36rem]/widget-card:items-start"
                    />
                </WidgetCardContent>
            )
        case 'session_replay_enabled':
            return (
                <WidgetCardContent className={className}>
                    <WidgetCardProductIntroduction
                        productName="Session replay"
                        productKey={ProductKey.SESSION_REPLAY}
                        thingName="recording"
                        titleOverride={availability.unavailableTitle}
                        description={availability.unavailableReason}
                        isEmpty
                        docsURL={availability.docsHref}
                        actionElementOverride={
                            <LemonButton type="primary" to={urls.settings('project-replay', 'replay')}>
                                {availability.setupActionLabel}
                            </LemonButton>
                        }
                    />
                </WidgetCardContent>
            )
        default: {
            const _exhaustive: never = availability.requirement
            return _exhaustive
        }
    }
}
