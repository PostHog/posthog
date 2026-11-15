import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import type { IntegrationKind } from '~/types'

interface IntegrationAccessRequestProps {
    kind: IntegrationKind
    name: string
}

export function IntegrationAccessRequest({ kind, name }: IntegrationAccessRequestProps): JSX.Element {
    const { accessRequestReason, accessRequestLoading, requestedAccessKinds } = useValues(integrationsLogic)
    const { setAccessRequestReason, requestIntegrationAccess } = useActions(integrationsLogic)

    if (requestedAccessKinds.includes(kind)) {
        return (
            <LemonBanner type="success" className="w-full">
                Request sent. Your project admins have been notified and can connect {name}.
            </LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-3 w-full">
            <LemonBanner type="info" className="w-full">
                You don’t have access to connect {name}. Tell your project admins why you need it and we'll email them.
            </LemonBanner>
            <LemonTextArea
                value={accessRequestReason}
                onChange={setAccessRequestReason}
                placeholder={`Why does your team need ${name}?`}
                minRows={3}
                maxLength={2000}
            />
            <LemonButton
                type="primary"
                fullWidth
                center
                loading={accessRequestLoading}
                disabledReason={!accessRequestReason.trim() ? 'Add a short note for your admins' : undefined}
                onClick={() => requestIntegrationAccess({ kind: kind })}
            >
                Request {name}
            </LemonButton>
        </div>
    )
}
