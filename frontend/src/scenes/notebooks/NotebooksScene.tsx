import './NotebookScene.scss'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonTab, LemonTabs, LemonTag, lemonToast } from '@posthog/lemon-ui'
import { Breadcrumb } from '@sentry/react'
import { actions, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { router, urlToAction } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { base64Encode, capitalizeFirstLetter } from 'lib/utils'
import { getTextFromFile, selectFiles } from 'lib/utils/file-utils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NotebooksTab } from '~/types'

import { NotebookCanvas } from './NotebookCanvasScene'
import { NotebooksTable } from './NotebooksTable/NotebooksTable'

export const scene: SceneExport = {
    component: NotebooksScene,
}

const TABS: LemonTab<NotebooksTab>[] = [
    {
        key: NotebooksTab.Notebooks,
        label: 'Notebooks',
        content: <TabNotebooks />,
        link: urls.notebooks(),
    },
    {
        key: NotebooksTab.Canvas,
        label: (
            <>
                Canvas
                <LemonTag className="ml-2" type="highlight">
                    NEW
                </LemonTag>
            </>
        ),
        content: <NotebookCanvas />,
        link: urls.canvas(),
    },
]

const notebooksSceneLogic = kea([
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
                    key: Scene.Notebooks,
                    name: `Notebooks`,
                    path: urls.notebooks(),
                },
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

function TabNotebooks(): JSX.Element {
    return (
        <>
            <PageHeader
                buttons={
                    <>
                        <LemonMenu
                            items={[
                                {
                                    label: 'Load from JSON',
                                    onClick: () => {
                                        void selectFiles({
                                            contentType: 'application/json',
                                            multiple: false,
                                        })
                                            .then((files) => getTextFromFile(files[0]))
                                            .then((text) => {
                                                const data = JSON.parse(text)
                                                if (data.type !== 'doc') {
                                                    throw new Error('Not a notebook')
                                                }

                                                // Looks like a notebook
                                                router.actions.push(
                                                    urls.canvas(),
                                                    {},
                                                    {
                                                        '🦔': base64Encode(text),
                                                    }
                                                )
                                            })
                                            .catch((e) => {
                                                lemonToast.error(e.message)
                                            })
                                    },
                                },
                            ]}
                        >
                            <LemonButton icon={<IconEllipsis />} size="small" />
                        </LemonMenu>
                        <LemonButton data-attr="new-notebook" to={urls.notebook('new')} type="primary">
                            New notebook
                        </LemonButton>
                    </>
                }
            />

            <NotebooksTable />
        </>
    )
}

export function NotebooksScene(): JSX.Element {
    const { tab } = useValues(notebooksSceneLogic)
    const { setTab } = useActions(notebooksSceneLogic)

    return (
        <>
            <LemonTabs activeKey={tab} onChange={(t) => setTab(t)} tabs={TABS} />
        </>
    )
}
