import { actions, kea, listeners, path, props, reducers } from 'kea'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import type { editorSceneLogicType } from './editorSceneLogicType'

export const renderTableCount = (count: undefined | number): null | JSX.Element => {
    if (!count) {
        return null
    }

    return (
        <span className="text-xs mr-1 italic text-[color:var(--color-text-secondary-3000)]">
            {`(${new Intl.NumberFormat('en', {
                notation: 'compact',
                compactDisplay: 'short',
            })
                .format(count)
                .toLowerCase()})`}
        </span>
    )
}

export interface EditorSceneLogicProps {
    tabId: string
}

export const editorSceneLogic = kea<editorSceneLogicType>([
    path(['data-warehouse', 'editor', 'editorSceneLogic']),
    props({} as EditorSceneLogicProps),
    tabAwareScene(),
    actions({
        reportAIQueryPrompted: true,
        reportAIQueryAccepted: true,
        reportAIQueryRejected: true,
        reportAIQueryPromptOpen: true,
        setWasPanelActive: (wasPanelActive: boolean) => ({ wasPanelActive }),
    }),
    reducers(() => ({
        wasPanelActive: [
            false,
            {
                setWasPanelActive: (_, { wasPanelActive }) => wasPanelActive,
            },
        ],
        panelExplicitlyClosed: [
            false,
            {
                [panelLayoutLogic.actionTypes.closePanel]: () => true,
            },
        ],
    })),
    listeners(() => ({
        reportAIQueryPrompted: () => {
            posthog.capture('ai_query_prompted')
        },
        reportAIQueryAccepted: () => {
            posthog.capture('ai_query_accepted')
        },
        reportAIQueryRejected: () => {
            posthog.capture('ai_query_rejected')
        },
        reportAIQueryPromptOpen: () => {
            posthog.capture('ai_query_prompt_open')
        },
    })),
    urlToAction(({ values }) => ({
        [urls.sqlEditor()]: () => {
            if (!values.panelExplicitlyClosed) {
                panelLayoutLogic.actions.showLayoutPanel(true)
                panelLayoutLogic.actions.setActivePanelIdentifier('Database')
                panelLayoutLogic.actions.toggleLayoutPanelPinned(true)
            }
        },
        '*': () => {
            if (router.values.location.pathname !== urls.sqlEditor()) {
                panelLayoutLogic.actions.clearActivePanelIdentifier()
                panelLayoutLogic.actions.toggleLayoutPanelPinned(false)
                panelLayoutLogic.actions.showLayoutPanel(false)
            }
        },
    })),
])
