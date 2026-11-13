import { useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { relationshipsLogic } from '../relationshipsLogic'
import { CatalogRelationshipsTable } from './CatalogRelationshipsTable'
import { CatalogRelationshipsToolbar } from './CatalogRelationshipsToolbar'
import { JoinEditorDialog } from './JoinEditorDialog'
import { RelationshipProposalDialog } from './RelationshipProposalDialog'

const SKELETON_ROWS = 5

function LoadingRows(): JSX.Element {
    return (
        <div className="flex flex-col gap-2" aria-busy="true">
            {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
            ))}
        </div>
    )
}

export function CatalogRelationshipsSection(): JSX.Element {
    const { rows, proposalsLoading, joinsLoading } = useValues(relationshipsLogic)

    return (
        <section aria-label="Relationships" className="flex flex-col gap-3" data-attr="data-catalog-relationships">
            <CatalogRelationshipsToolbar />
            {(proposalsLoading || joinsLoading) && rows.length === 0 ? <LoadingRows /> : <CatalogRelationshipsTable />}
            <RelationshipProposalDialog />
            <JoinEditorDialog />
        </section>
    )
}
