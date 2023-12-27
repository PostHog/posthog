import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { IconNotebook } from 'scenes/notebooks/IconNotebook'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'

export function NotebookButton(): JSX.Element {
    const { toggleVisibility } = useActions(notebookPanelLogic)

    return (
        <LemonButton
            icon={<IconNotebook />}
            onClick={toggleVisibility}
            status="primary-alt"
            size="small"
            type="secondary"
        >
            Notebooks
        </LemonButton>
    )
}
