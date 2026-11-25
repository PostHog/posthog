import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { AvailableFeature } from '~/types'

import { sidepanelTicketsLogic } from 'products/conversations/frontend/components/SidePanel/sidepanelTicketsLogic'

export function SSFSetting(): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)
    const { canCreateTicket } = useValues(sidepanelTicketsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const disabledReason = canCreateTicket
        ? undefined
        : "Your plan doesn't include support tickets. Upgrade your plan to request access."

    const requestAccess = (): void =>
        openSupportForm({
            kind: 'support',
            message: "I'd like to request access to SSF (Shared Signals Framework).",
            isEmailFormOpen: true,
        })

    if (todayRailNav) {
        return (
            <PayGateMini feature={AvailableFeature.SSF} featureDetail="organization-ssf">
                <div className="max-w-160 flex flex-col items-start gap-2">
                    <Text size="xs" render={<p className="m-0" />}>
                        SSF support is currently in closed beta. Request access if you would like to gain access.
                    </Text>
                    <Button
                        variant="primary"
                        data-attr="ssf-request-access"
                        disabledReason={disabledReason}
                        onClick={requestAccess}
                    >
                        Request access
                    </Button>
                </div>
            </PayGateMini>
        )
    }

    return (
        <PayGateMini feature={AvailableFeature.SSF} featureDetail="organization-ssf">
            <div className="max-w-160 flex flex-col items-start gap-3">
                <p className="m-0">
                    SSF support is currently in closed beta. Request access if you would like to gain access.
                </p>
                <LemonButton
                    type="primary"
                    data-attr="ssf-request-access"
                    disabledReason={disabledReason}
                    onClick={requestAccess}
                >
                    Request access
                </LemonButton>
            </div>
        </PayGateMini>
    )
}
