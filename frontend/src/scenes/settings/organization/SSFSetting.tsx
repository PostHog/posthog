import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { supportLogic } from 'lib/components/Support/supportLogic'

import { AvailableFeature } from '~/types'

export function SSFSetting(): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    return (
        <PayGateMini feature={AvailableFeature.SSF} featureDetail="organization-ssf">
            <div className="max-w-160 flex flex-col items-start gap-3">
                <p className="m-0">
                    SSF support is currently in closed beta. Request access if you would like to gain access.
                </p>
                <LemonButton
                    type="primary"
                    data-attr="ssf-request-access"
                    onClick={() =>
                        openSupportForm({
                            kind: 'support',
                            message: "I'd like to request access to SSF (Shared Signals Framework).",
                        })
                    }
                >
                    Request access
                </LemonButton>
            </div>
        </PayGateMini>
    )
}
