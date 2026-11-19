import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { supportLogic } from 'lib/components/Support/supportLogic'

import { AvailableFeature } from '~/types'

import { sidepanelTicketsLogic } from 'products/conversations/frontend/components/SidePanel/sidepanelTicketsLogic'

export function SSFSetting(): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)
    const { canCreateTicket } = useValues(sidepanelTicketsLogic)

    return (
        <PayGateMini feature={AvailableFeature.SSF} featureDetail="organization-ssf">
            <div className="max-w-160 flex flex-col items-start gap-3">
                <p className="m-0">
                    SSF support is currently in closed beta. Request access if you would like to gain access.
                </p>
                <LemonButton
                    type="primary"
                    data-attr="ssf-request-access"
                    disabledReason={
                        canCreateTicket
                            ? undefined
                            : "Your plan doesn't include support tickets. Upgrade your plan to request access."
                    }
                    onClick={() =>
                        openSupportForm({
                            kind: 'support',
                            message: "I'd like to request access to SSF (Shared Signals Framework).",
                            isEmailFormOpen: true,
                        })
                    }
                >
                    Request access
                </LemonButton>
            </div>
        </PayGateMini>
    )
}
