import { useValues } from 'kea'

import * as stopPng from '@posthog/brand/hoggies/png/stop'
import { LemonButton, LemonCard, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { SupportModalButton } from 'scenes/authentication/shared/SupportModalButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { organizationDeactivatedLogic } from './organizationDeactivatedLogic'

const HedgehogStop = pngHoggie(stopPng)

export const scene: SceneExport = {
    component: OrganizationDeactivated,
    logic: organizationLogic,
}

export function OrganizationDeactivated(): JSX.Element {
    const { isNotActiveReason } = useValues(organizationLogic)
    const { isPausedForUnpaidInvoice, unpaidInvoiceLink } = useValues(organizationDeactivatedLogic)

    return (
        <div className="max-w-[600px] mx-auto px-2 py-8">
            <LemonCard>
                <div className="flex flex-col gap-4 items-center text-center">
                    <HedgehogStop className="w-52 h-52" />
                    <h3>Your organization has been deactivated. {isNotActiveReason}</h3>
                    {/* `ALLOWED_WHILE_BLOCKED` in posthog/middleware.py keeps billing reachable from here. */}
                    {isPausedForUnpaidInvoice && (
                        <>
                            <p className="text-secondary mb-0">
                                Access returns for everyone in your organization once the invoice is paid.
                            </p>
                            {unpaidInvoiceLink && (
                                <LemonButton
                                    type="primary"
                                    to={unpaidInvoiceLink}
                                    data-attr="organization-deactivated-pay-invoice"
                                >
                                    Pay invoice
                                </LemonButton>
                            )}
                            <Link to={urls.organizationBilling()} data-attr="organization-deactivated-billing">
                                Go to billing
                            </Link>
                        </>
                    )}
                    <SupportModalButton kind="support" billingIssue label="Contact support" />
                </div>
            </LemonCard>
        </div>
    )
}
