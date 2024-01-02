import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { BatchExportsEditForm } from './BatchExportEditForm'
import { batchExportsEditLogic, BatchExportsEditLogicProps } from './batchExportEditLogic'
import { batchExportsEditSceneLogic } from './batchExportEditSceneLogic'

export const scene: SceneExport = {
    component: BatchExportsEditScene,
    logic: batchExportsEditSceneLogic,
    paramsToProps: ({ params: { id } }: { params: { id?: string } }): BatchExportsEditLogicProps => ({
        id: id ?? 'new',
    }),
}

export function BatchExportsEditScene(): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    if (!hasAvailableFeature(AvailableFeature.DATA_PIPELINES)) {
        return <></>
    }
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
