import { useActions, useValues } from 'kea'
import { SupportForm, SupportFormButtons } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { useEffect } from 'react'
import { sidePanelStateLogic } from '../sidePanelStateLogic'
import { SidePanelTab } from '~/types'

export const SidePanelSupport = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const { selectedTab } = useValues(sidePanelStateLogic)

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
