import { useActions, useValues } from 'kea'
import { supportLogic } from './supportLogic'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SupportForm, SupportFormButtons } from './SupportForm'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function SupportModal({ loggedIn = true }: { loggedIn?: boolean }): JSX.Element | null {
    const { sendSupportRequest, isSupportFormOpen, sendSupportLoggedOutRequest, title } = useValues(supportLogic)
    const { closeSupportForm } = useActions(supportLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const is3000 = useFeatureFlag('POSTHOG_3000')
    // the support model can be shown when logged out, file upload is not offered to anonymous users

    if (!isCloudOrDev || is3000) {
        return null
    }

    return (
        <LemonModal
            isOpen={isSupportFormOpen}
            onClose={closeSupportForm}
            title={title}
            footer={
                <div className="flex items-center gap-2">
                    <SupportFormButtons onClose={() => closeSupportForm()} />
                </div>
            }
            hasUnsavedInput={loggedIn ? !!sendSupportRequest.message : !!sendSupportLoggedOutRequest.message}
        >
            <SupportForm />
        </LemonModal>
    )
}
