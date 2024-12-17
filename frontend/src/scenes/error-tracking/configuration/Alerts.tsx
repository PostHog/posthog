import { LemonButton } from '@posthog/lemon-ui'
import { useState } from 'react'
import { DestinationsTable } from 'scenes/pipeline/destinations/Destinations'

export default function Alerts(): JSX.Element {
    const [createAlert, setCreateAlert] = useState<boolean>(true)

    return createAlert ? (
        <div className="space-y-2">
            <DestinationsTable types={['error_tracking_alert']} hideKind hideFeedback />
            <LemonButton type="primary" onClick={() => setCreateAlert(true)}>
                Add alert
            </LemonButton>
        </div>
    ) : null
}
