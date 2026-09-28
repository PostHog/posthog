import { useActions } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export type ZendeskSetupModalProps = {
    isOpen: boolean
    onClose: () => void
    redirectUrl?: string
    beforeRedirect?: () => void
}

export function ZendeskSetupModal({
    isOpen,
    onClose,
    redirectUrl,
    beforeRedirect,
}: ZendeskSetupModalProps): JSX.Element {
    const [subdomain, setSubdomain] = useState('')
    const { reportIntegrationConnectClicked } = useActions(eventUsageLogic)
    const trimmed = subdomain.trim()

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Connect Zendesk"
            description="Enter the subdomain of your Zendesk account. You sign in to Zendesk on the next step."
            footer={
                <LemonButton
                    type="primary"
                    // nosemgrep: prefer-codegen-api-namespaced-integrations - the generated authorize URL takes no query params
                    to={api.integrations.authorizeUrl({
                        kind: 'zendesk',
                        next: redirectUrl ?? window.location.pathname,
                        extraParams: { subdomain: trimmed },
                    })}
                    disableClientSideRouting
                    disabledReason={!trimmed ? 'Enter your Zendesk subdomain' : undefined}
                    onClick={() => {
                        reportIntegrationConnectClicked('zendesk', 'zendesk', 'pipeline_config')
                        beforeRedirect?.()
                    }}
                >
                    Continue to Zendesk
                </LemonButton>
            }
        >
            <LemonField.Pure label="Zendesk subdomain">
                <LemonInput
                    value={subdomain}
                    onChange={setSubdomain}
                    placeholder="mycompany"
                    suffix={<span className="text-secondary">.zendesk.com</span>}
                    autoFocus
                />
            </LemonField.Pure>
        </LemonModal>
    )
}
