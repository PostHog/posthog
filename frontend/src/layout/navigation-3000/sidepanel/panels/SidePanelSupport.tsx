import { useActions, useValues } from 'kea'
import { SupportForm, SupportFormButtons } from 'lib/components/Support/SupportForm'
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

            <div className="p-3 max-w-160 w-full mx-auto">
                <SupportForm />
                <div className="flex items-center justify-end gap-2 mt-4">
                    <SupportFormButtons onClose={() => closeSupportForm()} />
                </div>
            </div>
        </>
    )
}
