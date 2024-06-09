import { useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { insightLogic } from 'scenes/insights/insightLogic'

import { alertDeletionWarningLogic } from './alertDeletionWarningLogic'

export function AlertDeletionWarning(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { shouldShow } = useValues(alertDeletionWarningLogic(insightProps))

    if (!shouldShow) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mb-4">
            The new version of the insight doesn't support alerts, so the existing alerts will be deleted.
        </LemonBanner>
    )
}
