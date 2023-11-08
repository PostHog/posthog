import { useActions, useValues } from 'kea'
import { NotebookLogicProps, notebookLogic } from './Notebook/notebookLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { IconDelete, IconEllipsis, IconExport, IconNotification, IconShare } from 'lib/lemon-ui/icons'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { notebooksModel } from '~/models/notebooksModel'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import './NotebookScene.scss'
import { openNotebookShareDialog } from './Notebook/NotebookShare'

export function NotebookMenu({ shortId }: NotebookLogicProps): JSX.Element {
    const { notebook, showHistory, isLocalOnly } = useValues(notebookLogic({ shortId }))
    const { exportJSON, setShowHistory } = useActions(notebookLogic({ shortId }))

    return (
        <LemonMenu
            items={[
                {
                    items: [
                        {
                            label: 'Export JSON',
                            icon: <IconExport />,
                            onClick: () => exportJSON(),
                        },
                        {
                            label: 'History',
                            icon: <IconNotification />,
                            onClick: () => setShowHistory(!showHistory),
                        },
                        !isLocalOnly && {
                            label: 'Share',
                            icon: <IconShare />,
                            onClick: () => openNotebookShareDialog({ shortId }),
                        },
                        !notebook?.is_template && {
                            label: 'Delete',
                            icon: <IconDelete />,
                            status: 'danger',

                            onClick: () => {
                                notebooksModel.actions.deleteNotebook(shortId, notebook?.title)
                                router.actions.push(urls.notebooks())
                            },
                        },
                    ],
                },
            ]}
            actionable
        >
            <LemonButton aria-label="more" icon={<IconEllipsis />} status="stealth" size="small" />
        </LemonMenu>
    )
}
