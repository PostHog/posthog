import { actions, kea, path, reducers, selectors, useActions, useValues } from 'kea'
import { urlToAction } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { DataWarehouseExternalScene } from 'scenes/data-warehouse/external/DataWarehouseExternalScene'
import { NotebookCanvas } from 'scenes/notebooks/NotebookCanvasScene'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, ExploreTab } from '~/types'

import { EventsScene } from './events/EventsScene'
import type { exploreSceneLogicType } from './ExploreSceneType'
import { LiveEventsTable } from './live-events/LiveEventsTable'

const exploreSceneLogic = kea<exploreSceneLogicType>([
    path(['scenes', 'events', 'exploreSceneLogic']),
    actions({
        setTab: (tab: ExploreTab) => ({ tab }),
    }),
    reducers({
        tab: [
            ExploreTab.SQL as ExploreTab,
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
                    key: Scene.Explore,
                    name: `Explore`,
                    path: urls.explore(),
                },
                {
                    key: tab,
                    name: capitalizeFirstLetter(tab),
                },
            ],
        ],
    }),
    urlToAction(({ actions }) => ({
        [urls.explore(':tab')]: ({ tab }) => {
            actions.setTab(tab as ExploreTab)
        },
    })),
])

export function ExploreScene(): JSX.Element {
    const { tab } = useValues(exploreSceneLogic)
    const { setTab } = useActions(exploreSceneLogic)

    return (
        <div className="flex flex-1 flex-col">
            <PageHeader tabbedPage />
            <LemonTabs
                className="flex-1"
                activeKey={tab}
                onChange={(t) => setTab(t)}
                tabs={[
                    {
                        key: ExploreTab.SQL,
                        label: 'SQL studio',
                        content: <DataWarehouseExternalScene />,
                        link: urls.explore(ExploreTab.SQL),
                    },
                    {
                        key: ExploreTab.Events,
                        label: 'Events',
                        content: <EventsScene />,
                        link: urls.explore(ExploreTab.Events),
                    },
                    {
                        key: ExploreTab.LiveEvents,
                        label: 'Live events',
                        content: <LiveEventsTable />,
                        link: urls.explore(ExploreTab.LiveEvents),
                    },
                    {
                        key: ExploreTab.Canvas,
                        label: 'Canvas',
                        content: <NotebookCanvas />,
                        link: urls.explore(ExploreTab.Canvas),
                    },
                ]}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: ExploreScene,
    logic: exploreSceneLogic,
}
