import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'

import { BatchExportsEditForm } from './BatchExportEditForm'
import { BatchExportsEditLogicProps } from './batchExportEditLogic'
import { batchExportsEditSceneLogic } from './batchExportEditSceneLogic'

export const scene: SceneExport = {
    component: BatchExportsEditScene,
    logic: batchExportsEditSceneLogic,
    paramsToProps: ({ params: { id } }: { params: { id?: string } }): BatchExportsEditLogicProps => ({
        id: id ?? 'new',
    }),
}

export function BatchExportsEditScene(): JSX.Element {
    const { id } = useValues(batchExportsEditSceneLogic)

    return (
        <>
            <PageHeader />

            <div className="my-8" />

            <BatchExportsEditForm id={id} />
        </>
    )
}
