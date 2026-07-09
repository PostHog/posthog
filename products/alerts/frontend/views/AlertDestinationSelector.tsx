import { INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID } from 'lib/constants'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { buildAlertFilterConfig } from 'products/alerts/frontend/logic/alerts'

export interface AlertDestinationSelectorProps {
    alertId: string
    insightShortId: InsightShortId
}

export function AlertDestinationSelector({ alertId, insightShortId }: AlertDestinationSelectorProps): JSX.Element {
    const returnTo = `${urls.insightAlerts(insightShortId)}?alert_id=${alertId}`

    return (
        <LinkedHogFunctions
            type="internal_destination"
            subTemplateIds={[INSIGHT_ALERT_FIRING_SUB_TEMPLATE_ID]}
            hideFeedback={true}
            forceFilterGroups={[buildAlertFilterConfig(alertId)]}
            queryParams={{ returnTo }}
        />
    )
}
