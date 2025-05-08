import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'
import { HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES } from 'scenes/pipeline/hogfunctions/sub-templates/sub-templates'

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <LinkedHogFunctions
            logicKey="error-tracking"
            type="internal_destination"
            subTemplateId="error-tracking-issue-created"
            filters={HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created']?.filters ?? {}}
        />
    )
}
