import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { viewLinkLogic } from 'products/data_warehouse/frontend/shared/logics/viewLinkLogic'

import { RelationshipRow, relationshipsLogic } from '../relationshipsLogic'
import { RejectRelationshipDialog } from './RejectRelationshipDialog'

const WORKING_REASON = 'Saving the last change'

function JoinMenu({ row }: { row: RelationshipRow }): JSX.Element | null {
    const { joinsById } = useValues(relationshipsLogic)
    const { deleteJoin } = useActions(relationshipsLogic)
    const { toggleEditJoinModal } = useActions(viewLinkLogic)
    const join = row.joinId ? joinsById[row.joinId] : null
    if (!join) {
        return null
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon"
                        aria-label={`More actions for ${row.fieldName}`}
                        className="text-muted-foreground"
                        data-attr="data-catalog-relationships-row-actions"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-40">
                <DropdownMenuItem
                    onClick={() => toggleEditJoinModal(join)}
                    data-attr="data-catalog-relationships-edit-join"
                >
                    Edit
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    variant="destructive"
                    onClick={() => deleteJoin(join)}
                    data-attr="data-catalog-relationships-delete-join"
                >
                    Delete
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function ReviewButtons({ proposalId }: { proposalId: string }): JSX.Element {
    const { actionsInFlight } = useValues(relationshipsLogic)
    const { acceptProposal } = useActions(relationshipsLogic)
    const [rejecting, setRejecting] = useState(false)
    const inFlight = !!actionsInFlight[proposalId]

    return (
        <div className="flex justify-end gap-1">
            <Button
                variant="primary"
                size="sm"
                loading={inFlight}
                onClick={() => acceptProposal(proposalId)}
                data-attr="data-catalog-relationships-accept"
            >
                Accept
            </Button>
            <Button
                variant="outline"
                size="sm"
                disabledReason={inFlight ? WORKING_REASON : undefined}
                onClick={() => setRejecting(true)}
                data-attr="data-catalog-relationships-reject"
            >
                Reject
            </Button>
            <RejectRelationshipDialog proposalId={proposalId} open={rejecting} onClose={() => setRejecting(false)} />
        </div>
    )
}

export function CatalogRelationshipActions({ row }: { row: RelationshipRow }): JSX.Element | null {
    if (row.rowStatus === 'active') {
        return <JoinMenu row={row} />
    }
    if (row.rowStatus === 'pending' && row.proposalId) {
        return <ReviewButtons proposalId={row.proposalId} />
    }
    return null
}
