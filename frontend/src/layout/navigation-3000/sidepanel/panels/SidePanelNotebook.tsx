import { useActions, useValues } from 'kea'
import { NotebookPopoverCard } from 'scenes/notebooks/Notebook/NotebookPopover'
import { notebookPopoverLogic } from 'scenes/notebooks/Notebook/notebookPopoverLogic'
import { sidePanelLogic } from '../sidePanelLogic'
import { useEffect } from 'react'

export const SidePanelNotebook = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelLogic)
    const { selectedTab } = useValues(sidePanelLogic)

    const { visibility } = useValues(notebookPopoverLogic)
    const { setVisibility } = useActions(notebookPopoverLogic)

    // useEffect(() => {
    //     // When something sets the popover to hidden - close the side panel
    //     return () => {
    //         if (selectedTab === 'notebook') {
    //             closeSidePanel()
    //         }
    //     }
    // }, [visibility === 'hidden'])

    useEffect(() => {
        setVisibility('visible')
        // On unmount - hide the popover
        return () => {
            setVisibility('hidden')
        }
    }, [])

    return <NotebookPopoverCard />
}
