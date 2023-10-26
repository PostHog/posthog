import { useActions, useValues } from 'kea'
import { SupportForm, SupportFormButtons } from 'lib/components/Support/SupportForm'
import { sidePanelLogic } from '../sidePanelLogic'
import { supportLogic } from 'lib/components/Support/supportLogic'

export const SidePanelSupport = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelLogic)

    const { title } = useValues(supportLogic)

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
