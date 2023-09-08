import { LemonButton, LemonModal, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { databaseSceneLogic } from 'scenes/data-management/database/databaseSceneLogic'
import { DataWarehousePageTabs, DataWarehouseTab } from '../DataWarehousePageTabs'
import { DatabaseTablesContainer } from 'scenes/data-management/database/DatabaseTables'
import { useState } from 'react'
import { ViewLinkForm } from '../ViewLinkModal'

export const scene: SceneExport = {
    component: DataWarehousePosthogScene,
    logic: databaseSceneLogic,
}

export function DataWarehousePosthogScene(): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <div>
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Data Warehouse
                        <LemonTag type="warning" className="uppercase">
                            Beta
                        </LemonTag>
                    </div>
                }
                caption={
                    <div>
                        These are the database tables you can query under SQL insights with{' '}
                        <a href="https://posthog.com/manual/hogql" target="_blank">
                            HogQL
                        </a>
                        .
                    </div>
                }
                buttons={
                    <LemonButton type="primary" data-attr="new-data-warehouse-table" onClick={() => setIsOpen(true)}>
                        Link table to view
                    </LemonButton>
                }
            />
            <DataWarehousePageTabs tab={DataWarehouseTab.Posthog} />
            <DatabaseTablesContainer />
            <TableToLinkModal isOpen={isOpen} onClose={() => setIsOpen(false)} />
        </div>
    )
}

interface TableToLinkModalProps {
    isOpen: boolean
    onClose: () => void
}

function TableToLinkModal({ isOpen, onClose }: TableToLinkModalProps): JSX.Element {
    return (
        <LemonModal
            title="Link view to table"
            description={
                <span>
                    Define a join between the table and view. <b>All</b> fields from the view will be accessible in
                    queries at the top level without needing to explicitly join the view.
                </span>
            }
            isOpen={isOpen}
            onClose={onClose}
            width={600}
        >
            <ViewLinkForm tableSelectable={true} />
        </LemonModal>
    )
}
