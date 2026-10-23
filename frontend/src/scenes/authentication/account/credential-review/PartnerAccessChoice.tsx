import { decode } from 'he'
import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import type { ConnectedAppApi } from '~/generated/core/api.schemas'

import { credentialReviewLogic } from './credentialReviewLogic'

export function PartnerAccessChoice({ app }: { app: ConnectedAppApi }): JSX.Element {
    const { keptPartnerIds, revokingAppId, isCompleting } = useValues(credentialReviewLogic)
    const { keepPartnerConnected, disconnectPartner } = useActions(credentialReviewLogic)

    // Name is HTML-escaped at ingestion; decode for display (see posthog/api/oauth/client_name.py).
    const name = decode(app.name)
    const isKept = keptPartnerIds.includes(app.id)
    const isRevoking = revokingAppId === app.id

    return (
        <LemonCard hoverEffect={false} className="p-4 flex flex-wrap items-center justify-between gap-3">
            <div className="grow basis-60 min-w-0">
                <div className="font-semibold">{name}</div>
                <p className="text-secondary mb-0">
                    {`${name} set up your PostHog organization and has access to your account. Keep it connected only if you asked ${name} to do this.`}
                </p>
            </div>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    active={isKept}
                    icon={isKept ? <IconCheck /> : undefined}
                    onClick={() => keepPartnerConnected(app.id)}
                    disabledReason={isRevoking ? `Disconnecting ${name}` : null}
                    data-attr="credential-review-keep-partner"
                >
                    Keep connected
                </LemonButton>
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    loading={isRevoking}
                    onClick={() => disconnectPartner(app.id)}
                    disabledReason={
                        isCompleting
                            ? 'Saving your review'
                            : revokingAppId && !isRevoking
                              ? 'Wait for the other app to disconnect'
                              : null
                    }
                    data-attr="credential-review-disconnect-partner"
                >
                    Disconnect
                </LemonButton>
            </div>
        </LemonCard>
    )
}
