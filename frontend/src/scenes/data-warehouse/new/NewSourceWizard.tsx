import { LemonButton } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import SourceModal from '../external/SourceModal'
import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'

export const scene: SceneExport = {
    component: NewSourceWizard,
    logic: dataWarehouseTableLogic,
}
export function NewSourceWizard(): JSX.Element {
    return (
        <>
            <PageHeader
                buttons={
                    <>
                        <LemonButton
                            type="secondary"
                            center
                            data-attr="source-form-cancel-button"
                            to={urls.dataWarehouse()}
                        >
                            Cancel
                        </LemonButton>
                    </>
                }
            />
            <SourceModal />
        </>
    )
}
