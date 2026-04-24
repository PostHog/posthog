import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { urls } from 'scenes/urls'

import { limitExceededLogic } from './limitExceededLogic'

export function LimitExceededModal(): JSX.Element | null {
    const { isOpen, limitExceededPayload, request } = useValues(limitExceededLogic)
    const { hideLimitExceededModal } = useActions(limitExceededLogic)

    if (!isOpen || !limitExceededPayload) {
        return null
    }

    const limitLabel = request?.limit_description ?? limitExceededPayload.limit_key

    return (
        <LemonModal
            title="Whoa there, you've hit a limit"
            description={`${limitLabel} is capped at ${limitExceededPayload.limit}. No more for now.`}
            isOpen={isOpen}
            onClose={hideLimitExceededModal}
            footer={
                <div className="flex w-full items-center justify-end gap-2">
                    <LemonButton type="tertiary" onClick={hideLimitExceededModal}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        to={urls.settings('environment-limit-requests')}
                        onClick={hideLimitExceededModal}
                    >
                        View your limit requests
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-3 max-w-lg">
                <p className="m-0">
                    <strong>We already pinged our team</strong> to take a look. You don't need to do anything else.
                </p>
                <p className="m-0 text-muted">
                    Want to speed things up? Add context to the request in your settings. The more specific, the faster
                    we can say yes.
                </p>
            </div>
        </LemonModal>
    )
}
