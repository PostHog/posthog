import { router } from 'kea-router'
import { PaymentsTabs } from 'scenes/payments/components/PaymentsTabs'
import { Settings } from 'scenes/settings/Settings'

const SETTINGS_LOGIC_KEY = 'paymentsSettings'

export function PaymentsSettingsScene(): JSX.Element {
    return (
        <>
            <PaymentsTabs />
            <Settings
                logicKey={SETTINGS_LOGIC_KEY}
                sectionId="environment-payments"
                settingId={router.values.searchParams.sectionId || 'payments-webhooks'}
                handleLocally
            />
        </>
    )
}
