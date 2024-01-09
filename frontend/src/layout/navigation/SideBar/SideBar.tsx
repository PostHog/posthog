import { ActivationSidebar } from 'lib/components/ActivationSidebar/ActivationSidebar'
import { NotebookPopover } from 'scenes/notebooks/NotebookPanel/NotebookPopover'

export function SideBar(): JSX.Element {
    return (
        <div>
            <NotebookPopover />
            <ActivationSidebar />
        </div>
    )
}
