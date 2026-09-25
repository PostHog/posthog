import { useValues } from 'kea'

import * as stopPng from '@posthog/brand/hoggies/png/stop'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { SupportModalButton } from 'scenes/authentication/shared/SupportModalButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

const HedgehogStop = pngHoggie(stopPng)

export const scene: SceneExport = {
    component: OrganizationDeactivated,
    logic: organizationLogic,
}

export function OrganizationDeactivated(): JSX.Element {
    const { isNotActiveReason } = useValues(organizationLogic)
    const { isCloud } = useValues(preflightLogic)

    return (
        <div className="max-w-[600px] mx-auto px-2 py-8">
            <LemonCard>
                <div className="flex flex-col gap-4 items-center text-center">
                    <HedgehogStop className="w-52 h-52" />
                    <h3>Your organization has been deactivated. {isNotActiveReason}</h3>
                    {/* `ALLOWED_WHILE_BLOCKED` in posthog/middleware.py keeps billing reachable from here. */}
                    {isCloud && (
                        <>
                            <p className="text-secondary mb-0">
                                If this is because of an unpaid balance, you can pay it in billing and get your
                                organization back.
                            </p>
                            <LemonButton
                                type="primary"
                                to={urls.organizationBilling()}
                                data-attr="organization-deactivated-billing"
                            >
                                Go to billing
                            </LemonButton>
                        </>
                    )}
                    <SupportModalButton kind="support" billingIssue label="Contact support" />
                </div>
            </LemonCard>
        </div>
    )
}
