import { useActions, useValues } from 'kea'
import { SupportForm, SupportFormButtons } from 'lib/components/Support/SupportForm'
import { SidePanelTab, sidePanelLogic } from '../sidePanelLogic'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { useEffect } from 'react'

export const SidePanelSupport = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelLogic)
    const { selectedTab } = useValues(sidePanelLogic)

    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Feedback) })
    const { title } = useValues(theLogic)
    const { closeSupportForm } = useActions(theLogic)

    useEffect(() => {
        return () => closeSupportForm()
    }, [selectedTab])

    return (
        <div className="p-3 max-w-160 w-full mx-auto">
            <h1>{title}</h1>

            <SupportForm />

            <div className="flex items-center justify-end gap-2">
                <SupportFormButtons onClose={() => closeSidePanel()} />
            </div>
        </div>
    )
}
