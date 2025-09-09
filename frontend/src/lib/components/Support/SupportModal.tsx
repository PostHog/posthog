import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { createRoot } from 'react-dom/client'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import { SupportForm } from './SupportForm'
import { supportLogic } from './supportLogic'

function SupportModal({ onAfterClose }: { onAfterClose: () => void }): JSX.Element | null {
    const { sendSupportRequest, isSupportFormOpen, title } = useValues(supportLogic)
    const { closeSupportForm, resetSendSupportRequest } = useActions(supportLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { sidePanelAvailable } = useValues(sidePanelStateLogic)

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
                        form="support-modal-form"
                        type="secondary"
                        onClick={() => {
                            closeSupportForm()
                            resetSendSupportRequest()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton form="support-modal-form" htmlType="submit" type="primary" data-attr="submit">
                        Submit
                    </LemonButton>
                </div>
            }
            hasUnsavedInput={!!sendSupportRequest.message}
            onAfterClose={onAfterClose}
        >
            <SupportForm />
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
