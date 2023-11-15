import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SupportForm, SupportFormButtons } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { useEffect } from 'react'

import { SidePanelTab } from '~/types'

import { sidePanelStateLogic } from '../sidePanelStateLogic'

export const SidePanelSupport = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const { selectedTab } = useValues(sidePanelStateLogic)

    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Support) })
    const { title } = useValues(theLogic)
    const { closeSupportForm } = useActions(theLogic)

    useEffect(() => {
        return () => closeSupportForm()
    }, [selectedTab])

    return (
        <div className="p-3 max-w-160 w-full mx-auto">
            <h2 className="text-lg font-bold mb-2">{title}</h2>
            <LemonDivider />
            <SupportForm />
            <div className="flex items-center justify-end gap-2 mt-4">
                <SupportFormButtons onClose={() => closeSidePanel()} />
            </div>
        </div>
    )
}
