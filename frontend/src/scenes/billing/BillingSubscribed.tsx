import { PropsWithChildren } from 'react'
import { helpButtonLogic } from 'lib/components/HelpButton/HelpButton'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { dayjs } from 'lib/dayjs'
import { billingLogic } from './billingLogic'
import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { IconCheckmark } from 'lib/components/icons'

export const scene: SceneExport = {
    component: BillingSubscribed,
}

export function BillingSubscribedTheme({ children }: PropsWithChildren<unknown>): JSX.Element {
    const { toggleHelp } = useActions(helpButtonLogic)

    return (
        <BridgePage view={'billing'}>
            {children}

            <LemonDivider dashed className="my-4" />
            <div className="text-center">
                Have questions? <Link onClick={toggleHelp}>Get help</Link>
            </div>
        </BridgePage>
    )
}

export function BillingSubscribed(): JSX.Element {
    const { billing, billingSuccessRedirect } = useValues(billingLogic)

    return (
        <BillingSubscribedTheme>
            <div className="flex items-center justify-center gap-2">
                <IconCheckmark className="text-success text-3xl mb-2" />
                <h2>You're all set!</h2>
            </div>
            <p>
                You are now subscribed
                {billing?.is_billing_active && billing.plan && (
                    <>
                        {' '}
                        to the <b>{billing.plan.name}</b>
                    </>
                )}{' '}
                and can use all the premium features immediately.
            </p>
            {billing?.plan?.key === 'standard' && (
                <p className="text-muted-alt">
                    You will be billed on each month on the <strong>{dayjs().format('D')}</strong>. If you ingest less
                    than 1M events, you will not be billed.
                </p>
            )}
            <p>
                Please reach out to <a href="mailto:hey@posthog.com">hey@posthog.com</a> if you have any billing
                questions.
            </p>
            <LemonButton className="cta-button" type="primary" center={true} fullWidth to={billingSuccessRedirect}>
                Finish
            </LemonButton>
        </BillingSubscribedTheme>
    )
}
