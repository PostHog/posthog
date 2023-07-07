import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { notebookSidebarLogic } from './Notebook/notebookSidebarLogic'
import { IconArrowRight } from 'lib/lemon-ui/icons'

export function NotebookSidebarPlaceholder(): JSX.Element {
    const { setNotebookSideBarShown } = useActions(notebookSidebarLogic)

    return (
        <div className="flex flex-col justify-center items-center h-full text-muted-alt mx-10">
            <h2 className="text-muted-alt">
                This Notebook is open in the sidebar <IconArrowRight />
            </h2>

            <p>
                You can navigate around PostHog and <b>drag and drop</b> thing into it. Or you can close the sidebar and
                it will be full screen here instead.
            </p>

            <LemonButton type="secondary" onClick={() => setNotebookSideBarShown(false)}>
                Open it here instead
            </LemonButton>
        </div>
    )
}
