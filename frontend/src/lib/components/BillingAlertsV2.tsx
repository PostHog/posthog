import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { cn } from 'lib/utils/css-classes'
import { billingLogic, BillingAlertConfig } from 'scenes/billing/billingLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { superpowersLogic } from './Superpowers/superpowersLogic'

export function BillingAlertsV2({ className }: { className?: string }): JSX.Element | null {
    const { fakeBillingAlert } = useValues(superpowersLogic)
    const { setFakeBillingAlert } = useActions(superpowersLogic)
    const { billingAlert: realBillingAlert, canAccessBilling } = useValues(billingLogic)

    const fakeBillingAlertConfig: BillingAlertConfig | null =
        fakeBillingAlert !== 'none'
            ? {
                  status: fakeBillingAlert,
                  title: `Fake ${fakeBillingAlert} billing alert`,
                  message: 'This is a fake billing alert triggered via Superpowers for testing purposes.',
              }
            : null

    const billingAlert = fakeBillingAlertConfig ?? realBillingAlert
    const { reportBillingAlertShown, reportBillingAlertActionClicked } = useActions(billingLogic)
    const { currentLocation } = useValues(router)
    const { sceneConfig } = useValues(sceneLogic)
    const [alertHidden, setAlertHidden] = useState(false)

    useEffect(() => {
        if (billingAlert?.pathName && currentLocation.pathname !== billingAlert?.pathName) {
            setAlertHidden(true)
        } else {
            setAlertHidden(false)
        }
        if (billingAlert && !fakeBillingAlertConfig) {
            reportBillingAlertShown(billingAlert)
        }
    }, [billingAlert, currentLocation]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (!billingAlert || alertHidden) {
        return null
    }

    const showButton =
        billingAlert.action || billingAlert.contactSupport || currentLocation.pathname !== urls.organizationBilling()

    const requiresHorizontalMargin =
        sceneConfig?.layout && ['app-raw', 'app-raw-no-header'].includes(sceneConfig.layout)

    const buttonProps = billingAlert.action
        ? billingAlert.action
        : billingAlert.contactSupport
          ? {
                to: 'mailto:sales@posthog.com',
                children: billingAlert.buttonCTA || 'Contact support',
                onClick: () => reportBillingAlertActionClicked(billingAlert),
            }
          : canAccessBilling
            ? {
                  to: urls.organizationBilling(),
                  children: 'Manage billing',
                  onClick: () => reportBillingAlertActionClicked(billingAlert),
              }
            : undefined

    return (
        <div className={cn('my-4', requiresHorizontalMargin && 'mx-4', className)}>
            <LemonBanner
                type={billingAlert.status}
                action={showButton ? buttonProps : undefined}
                onClose={
                    fakeBillingAlertConfig
                        ? () => setFakeBillingAlert('none')
                        : billingAlert.status !== 'error'
                          ? () => setAlertHidden(true)
                          : billingAlert.onClose
                            ? () => billingAlert.onClose?.()
                            : undefined
                }
                dismissKey={billingAlert.dismissKey}
            >
                <b>{billingAlert.title}</b>
                <br />
                {billingAlert.message}
            </LemonBanner>
        </div>
    )
}
