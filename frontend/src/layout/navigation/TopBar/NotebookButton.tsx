import { IconJournal } from 'lib/lemon-ui/icons'
import { useActions, useValues } from 'kea'
import { navigationLogic } from '~/layout/navigation/navigationLogic'

export function NotebookButton(): JSX.Element {
    const { mobileLayout } = useValues(navigationLogic)
    const { toggleNotebookSideBarBase, toggleNotebookSideBarMobile } = useActions(navigationLogic)

    return (
        <div
            className="h-10 items-center flex cursor-pointer text-primary-alt text-2xl"
            onClick={() => (mobileLayout ? toggleNotebookSideBarMobile() : toggleNotebookSideBarBase())}
        >
            <IconJournal />
        </div>
    )
}
