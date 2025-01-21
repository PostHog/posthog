import { LemonButton } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { DestinationsTable } from 'scenes/pipeline/destinations/Destinations'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

export function ErrorTrackingAlerting(): JSX.Element {
    return (
        <>
            <PageHeader
                buttons={
                    <LemonButton type="primary" to={urls.errorTrackingAlert('new')} className="flex">
                        Setup alert
                    </LemonButton>
                }
            />

            <LinkedHogFunctions
                logicKey="error-tracking-alerts"
                type="internal_destination"
                subTemplateId="error-tracking"
                filters={{
                    events: [
                        {
                            id: `$error_something`,
                            type: 'events',
                        },
                    ],
                }}
            />
            <DestinationsTable types={['error_tracking_alert']} hideKind hideFeedback />
        </>
    )
}
