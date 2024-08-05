import './NotebookScene.scss'

import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { Breadcrumb, NotebooksTab } from '~/types'

import type { notebooksSceneLogicType } from './notebooksSceneLogicType'

export const notebooksSceneLogic = kea<notebooksSceneLogicType>([
    path(['scenes', 'notebooks', 'notebooksSceneLogic']),
    actions({
        setTab: (tab: NotebooksTab) => ({ tab }),
    }),
    reducers({
        tab: [
            NotebooksTab.Notebooks as NotebooksTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (s) => [s.tab],
            (tab): Breadcrumb[] => [
                {
                    key: tab,
                    name: capitalizeFirstLetter(tab),
                },
            ],
        ],
    }),
    urlToAction(({ actions }) => ({
        [urls.notebooks()]: () => actions.setTab(NotebooksTab.Notebooks),
        [urls.canvas()]: () => actions.setTab(NotebooksTab.Canvas),
    })),
])
