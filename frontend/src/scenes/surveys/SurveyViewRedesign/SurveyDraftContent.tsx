import { IconRocket } from '@posthog/icons'

import { LaunchSurveyButton } from 'scenes/surveys/components/LaunchSurveyButton'

export function SurveyDraftContent(): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center py-16 gap-6 max-w-lg mx-auto text-center">
            <div className="flex flex-col items-center gap-4">
                <div className="w-14 h-14 rounded-full bg-primary-highlight flex items-center justify-center">
                    <IconRocket className="text-3xl text-primary" />
                </div>
                <div>
                    <h2 className="text-xl font-semibold m-0 mb-2">Ready to launch</h2>
                    <p className="text-muted m-0">
                        Your survey is configured and ready to start collecting responses. You can preview how it looks
                        in the sidebar.
                    </p>
                </div>
                <LaunchSurveyButton>Launch survey</LaunchSurveyButton>
            </div>
        </div>
    )
}
