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
    return (
        <>
            <PageHeader title={'Event explorer'} />
            <div className="pt-4 border-t" />
            <EventsScene />
        </>
    )
}
