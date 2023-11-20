import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { useValues } from 'kea'
import { BatchExportsEditLogicProps, batchExportsEditLogic } from './batchExportEditLogic'
import { batchExportsEditSceneLogic } from './batchExportEditSceneLogic'
import { BatchExportsEditForm } from './BatchExportEditForm'

export const scene: SceneExport = {
    component: BatchExportsEditScene,
    logic: batchExportsEditSceneLogic,
    paramsToProps: ({ params: { id } }: { params: { id?: string } }): BatchExportsEditLogicProps => ({
        id: id ?? 'new',
    }),
}

export function BatchExportsEditScene(): JSX.Element {
    const { id } = useValues(batchExportsEditSceneLogic)
    const { isNew } = useValues(batchExportsEditLogic({ id }))

    return (
        <>
            <PageHeader title={`${isNew ? 'New' : 'Edit'} batch export`} />

            <div className="my-8" />

            <BatchExportsEditForm id={id} />
        </>
    )
}
