import { ERROR_TRACKING_LOGIC_KEY } from 'scenes/error-tracking/utils'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES } from 'scenes/hog-functions/sub-templates/sub-templates'

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <LinkedHogFunctions
            logicKey={ERROR_TRACKING_LOGIC_KEY}
            type="internal_destination"
            subTemplateIds={['error-tracking-issue-created', 'error-tracking-issue-reopened']}
            filters={HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created']?.filters ?? {}}
        />
    )
}
