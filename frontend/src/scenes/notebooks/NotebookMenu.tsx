import './NotebookScene.scss'

import { IconClock, IconEllipsis, IconShare } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { IconDelete, IconExport } from 'lib/lemon-ui/icons'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { urls } from 'scenes/urls'

import { notebooksModel } from '~/models/notebooksModel'

import { notebookLogic, NotebookLogicProps } from './Notebook/notebookLogic'
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
                            icon: <IconClock />,
                            onClick: () => setShowHistory(!showHistory),
                        },
                        {
                            label: 'Share',
                            icon: <IconShare />,
                            onClick: () => openNotebookShareDialog({ shortId }),
                        },
                        !isLocalOnly &&
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
