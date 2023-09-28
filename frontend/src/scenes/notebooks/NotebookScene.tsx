import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { notebookLogic } from './Notebook/notebookLogic'
import { Notebook } from './Notebook/Notebook'
import { NotFound } from 'lib/components/NotFound'
import { NotebookSceneLogicProps, notebookSceneLogic } from './notebookSceneLogic'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { notebookPopoverLogic } from './Notebook/notebookPopoverLogic'
import { NotebookExpandButton, NotebookSyncInfo } from './Notebook/NotebookMeta'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import {
    IconArrowRight,
    IconDelete,
    IconEllipsis,
    IconExport,
    IconHelpOutline,
    IconNotification,
} from 'lib/lemon-ui/icons'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { notebooksModel } from '~/models/notebooksModel'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { LOCAL_NOTEBOOK_TEMPLATES } from './NotebookTemplates/notebookTemplates'
import './NotebookScene.scss'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

interface NotebookSceneProps {
    shortId?: string
}

export const scene: SceneExport = {
    component: NotebookScene,
    logic: notebookSceneLogic,
    paramsToProps: ({ params: { shortId } }: { params: NotebookSceneProps }): NotebookSceneLogicProps => ({
        shortId: shortId || 'missing',
    }),
}

export function NotebookScene(): JSX.Element {
    const { notebookId } = useValues(notebookSceneLogic)
    const { notebook, notebookLoading, conflictWarningVisible, showHistory } = useValues(
        notebookLogic({ shortId: notebookId })
    )
    const { exportJSON, setShowHistory } = useActions(notebookLogic({ shortId: notebookId }))
    const { selectNotebook, setVisibility } = useActions(notebookPopoverLogic)
    const { selectedNotebook, visibility } = useValues(notebookPopoverLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const buttonSize = featureFlags[FEATURE_FLAGS.POSTHOG_3000] ? 'small' : 'medium'

    if (!notebook && !notebookLoading && !conflictWarningVisible) {
        return <NotFound object="notebook" />
    }

    if (visibility === 'visible' && selectedNotebook === notebookId) {
        return (
            <div className="flex flex-col justify-center items-center h-full text-muted-alt mx-10">
                <h2 className="text-muted-alt">
                    This Notebook is open in the sidebar <IconArrowRight />
                </h2>

                <p>
                    You can navigate around PostHog and <b>drag and drop</b> thing into it. Or you can close the sidebar
                    and it will be full screen here instead.
                </p>

                <LemonButton type="secondary" onClick={() => setVisibility('hidden')}>
                    Open it here instead
                </LemonButton>
            </div>
        )
    }

    const isTemplate = notebook?.is_template

    return (
        <div className="NotebookScene">
            <div className="flex items-center justify-between border-b py-2 mb-2 sticky top-0 bg-bg-3000 z-10">
                <div className="flex gap-2 items-center">
                    {isTemplate && <LemonTag type="highlight">TEMPLATE</LemonTag>}
                    <UserActivityIndicator at={notebook?.last_modified_at} by={notebook?.last_modified_by} />
                </div>

                <div className="flex gap-2 items-center">
                    <NotebookSyncInfo shortId={notebookId} />

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
                                    !isTemplate && {
                                        label: 'Delete',
                                        icon: <IconDelete />,
                                        status: 'danger',

                                        onClick: () => {
                                            notebooksModel.actions.deleteNotebook(notebookId, notebook?.title)
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
                    <LemonButton
                        type="secondary"
                        icon={<IconHelpOutline />}
                        size={buttonSize}
                        onClick={() => {
                            selectNotebook(LOCAL_NOTEBOOK_TEMPLATES[0].short_id)
                            setVisibility('visible')
                        }}
                    >
                        Guide
                    </LemonButton>
                    <NotebookExpandButton type="secondary" size={buttonSize} />
                    <LemonButton
                        type="secondary"
                        size={buttonSize}
                        onClick={() => {
                            selectNotebook(notebookId)
                            setVisibility('visible')
                        }}
                        tooltip={
                            <>
                                Pins the notebook to the right, allowing you to view it while navigating the rest of
                                PostHog. This is great for dragging and dropping elements like Insights, Recordings or
                                even Feature Flags into your active Notebook.
                            </>
                        }
                    >
                        Pin to side
                    </LemonButton>
                </div>
            </div>

            <Notebook key={notebookId} shortId={notebookId} editable={!isTemplate} />
        </div>
    )
}
