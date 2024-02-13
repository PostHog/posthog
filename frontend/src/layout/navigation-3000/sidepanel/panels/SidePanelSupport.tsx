import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'

import { SidePanelTab } from '~/types'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

export const SidePanelSupport = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Support) })
    const { title } = useValues(theLogic)
    const { closeSupportForm } = useActions(theLogic)

    return (
        <>
            <SidePanelPaneHeader title={title} />

            <div className="overflow-y-auto">
                <div className="p-3 max-w-160 w-full mx-auto">
                    <SupportForm />

                    <footer>
                        <LemonButton
                            form="support-modal-form"
                            htmlType="submit"
                            type="primary"
                            data-attr="submit"
                            fullWidth
                            center
                            className="mt-4"
                        >
                            Submit
                        </LemonButton>
                        <LemonButton
                            form="support-modal-form"
                            type="secondary"
                            onClick={closeSupportForm}
                            fullWidth
                            center
                            className="mt-2"
                        >
                            Cancel
                        </LemonButton>
                    </footer>
                </div>
            </div>
        </>
    )
}
