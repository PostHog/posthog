import './NotebookScene.scss'

import { IconInfo, IconOpenSidebar } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { NotebookTarget } from '~/types'

import { Notebook } from './Notebook/Notebook'
import { NotebookLoadingState } from './Notebook/NotebookLoadingState'
import { notebookLogic } from './Notebook/notebookLogic'
import { NotebookExpandButton, NotebookSyncInfo } from './Notebook/NotebookMeta'
import { NotebookMenu } from './NotebookMenu'
import { notebookPanelLogic } from './NotebookPanel/notebookPanelLogic'
import { notebookSceneLogic, NotebookSceneLogicProps } from './notebookSceneLogic'
import { LOCAL_NOTEBOOK_TEMPLATES } from './NotebookTemplates/notebookTemplates'

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
    const { notebookId, loading } = useValues(notebookSceneLogic)
    const { notebook, conflictWarningVisible } = useValues(
        notebookLogic({ shortId: notebookId, target: NotebookTarget.Scene })
    )
    const { selectNotebook, closeSidePanel } = useActions(notebookPanelLogic)
    const { selectedNotebook, visibility } = useValues(notebookPanelLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const buttonSize = featureFlags[FEATURE_FLAGS.POSTHOG_3000] ? 'small' : 'medium'

    if (!notebook && !loading && !conflictWarningVisible) {
        return <NotFound object="notebook" />
    }

    if (visibility === 'visible' && selectedNotebook === notebookId) {
        return (
            <div className="flex flex-col justify-center items-center h-full text-muted-alt mx-10 flex-1">
                <h2 className="text-muted-alt">
                    This Notebook is open in the side panel <IconOpenSidebar />
                </h2>

                <p>
                    You can navigate around PostHog and <b>drag and drop</b> thing into it. Or you can close the sidebar
                    and it will be full screen here instead.
                </p>

                <LemonButton type="secondary" onClick={() => closeSidePanel()}>
                    Open it here instead
                </LemonButton>
            </div>
        )
    }

    const isTemplate = notebook?.is_template

    if (notebookId === 'new') {
        return <NotebookLoadingState />
    }

    return (
        <div className="NotebookScene">
            <div className="flex items-center justify-between border-b py-2 mb-2 sticky top-0 bg-bg-3000 z-10">
                <div className="flex gap-2 items-center">
                    {isTemplate && <LemonTag type="highlight">TEMPLATE</LemonTag>}
                    <UserActivityIndicator at={notebook?.last_modified_at} by={notebook?.last_modified_by} />
                </div>

                <div className="flex gap-2 items-center">
                    <NotebookSyncInfo shortId={notebookId} />

                    <NotebookMenu shortId={notebookId} />

                    <LemonButton
                        type="secondary"
                        icon={<IconInfo />}
                        size={buttonSize}
                        onClick={() => {
                            if (selectedNotebook === LOCAL_NOTEBOOK_TEMPLATES[0].short_id && visibility === 'visible') {
                                closeSidePanel()
                            } else {
                                selectNotebook(LOCAL_NOTEBOOK_TEMPLATES[0].short_id)
                            }
                        }}
                    >
                        {selectedNotebook === LOCAL_NOTEBOOK_TEMPLATES[0].short_id && visibility === 'visible'
                            ? 'Close '
                            : ''}
                        Guide
                    </LemonButton>
                    <NotebookExpandButton type="secondary" size={buttonSize} />
                    <LemonButton
                        type="secondary"
                        size={buttonSize}
                        onClick={() => {
                            selectNotebook(notebookId)
                        }}
                        tooltip={
                            <>
                                Opens the notebook in a side panel, that can be accessed from anywhere in the PostHog
                                app. This is great for dragging and dropping elements like insights, recordings or even
                                feature flags into your active notebook.
                            </>
                        }
                        sideIcon={<IconOpenSidebar />}
                    >
                        Open in side panel
                    </LemonButton>
                </div>
            </div>

            <Notebook key={notebookId} shortId={notebookId} editable={!isTemplate} />
        </div>
    )
}
