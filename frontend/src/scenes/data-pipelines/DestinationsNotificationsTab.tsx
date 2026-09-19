import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

export function DestinationsNotificationsTab(): JSX.Element {
    return (
        <SceneContent>
            <SceneSection
                description={
                    <>
                        These destinations deliver the alerts and other events that PostHog itself sends, such as an
                        insight alert that fires or a new error tracking issue. Create them from the product they belong
                        to, for example from an alert or from the error tracking settings.
                    </>
                }
            >
                <HogFunctionList
                    logicKey="data-pipelines-notifications"
                    type="internal_destination"
                    truncateDescriptions
                />
            </SceneSection>
        </SceneContent>
    )
}
