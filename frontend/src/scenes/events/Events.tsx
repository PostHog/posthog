import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { EventsScene } from 'scenes/events/EventsScene'

export const scene: SceneExport = {
    component: Events,
    // TODO!
    // NOTE: Removing the lines below because turbo mode messes up having two separate versions of this scene.
    //       It's a small price to pay. Put this back when the flag is removed.
    // logic: eventsTableLogic,
    // paramsToProps: ({ params: { fixedFilters } }) => ({ fixedFilters, key: 'EventsTable', sceneUrl: urls.events() }),
}

export function Events(): JSX.Element {
    // const canvasMode = useFeatureFlag('NOTEBOOK_CANVASES')

    // if (canvasMode) {
    //     return (
    //         <Notebook
    //             editable={true}
    //             shortId={`canvas-events`}
    //             mode="canvas"
    //             initialContent={{
    //                 type: 'doc',
    //                 content: [
    //                     {
    //                         type: 'ph-query',
    //                         attrs: {
    //                             height: null,
    //                             title: null,
    //                             __init: {
    //                                 expanded: true,
    //                                 showSettings: true,
    //                             },
    //                         },
    //                     },
    //                 ],
    //             }}
    //         />
    //     )
    // }

    return (
        <>
            <PageHeader title={'Event Explorer'} />
            <div className="pt-4 border-t" />
            <EventsScene />
        </>
    )
}
