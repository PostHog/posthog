import { useActions, useValues } from 'kea'
import { useEffect, useId } from 'react'
import { createRoot } from 'react-dom/client'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import { SupportForm } from './SupportForm'
import { supportLogic } from './supportLogic'

function SupportModal({ onAfterClose }: { onAfterClose: () => void }): JSX.Element | null {
    const { sendSupportRequest, isSupportFormOpen, title, isSendSupportRequestSubmitting, submitDisabledReason } =
        useValues(supportLogic)
    const { closeSupportForm, resetSendSupportRequest } = useActions(supportLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { sidePanelAvailable } = useValues(sidePanelStateLogic)
    // Unique per instance so the footer Submit can only ever target this form (see SupportForm's `id`)
    const formId = useId()

    useEffect(() => {
        if (!isCloudOrDev) {
            onAfterClose()
        }
    }, [isCloudOrDev]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (!isCloudOrDev || sidePanelAvailable) {
        return null
    }

    return (
        <LemonModal
            isOpen={isSupportFormOpen}
            onClose={closeSupportForm}
            title={title}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        form={formId}
                        type="secondary"
                        onClick={() => {
                            closeSupportForm()
                            resetSendSupportRequest()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form={formId}
                        htmlType="submit"
                        type="primary"
                        data-attr="submit"
                        loading={isSendSupportRequestSubmitting}
                        disabledReason={submitDisabledReason}
                    >
                        Submit
                    </LemonButton>
                </div>
            }
            hasUnsavedInput={!!sendSupportRequest.message}
            onAfterClose={onAfterClose}
        >
            <SupportForm id={formId} />
        </LemonModal>
    )
}

export const openSupportModal = (): void => {
    const div = document.createElement('div')
    const root = createRoot(div)
    function destroy(): void {
        root.unmount()
        if (div.parentNode) {
            div.parentNode.removeChild(div)
        }
    }

    document.body.appendChild(div)
    root.render(<SupportModal onAfterClose={destroy} />)
    return
}
