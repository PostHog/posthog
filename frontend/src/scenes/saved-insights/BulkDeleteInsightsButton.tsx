import { useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { projectLogic } from 'scenes/projectLogic'

export interface BulkDeleteInsightsResult {
    deleted: number[]
    errors: Array<{ id: number; reason: string }>
}

interface BulkDeleteInsightsButtonProps {
    selectedIds: ReadonlyArray<number>
    onSuccess?: () => void
}

export function BulkDeleteInsightsButton({ selectedIds, onSuccess }: BulkDeleteInsightsButtonProps): JSX.Element {
    const [loading, setLoading] = useState(false)
    const { currentProjectId } = useValues(projectLogic)

    const count = selectedIds.length
    const plural = count !== 1 ? 's' : ''

    const submit = async (): Promise<void> => {
        setLoading(true)
        try {
            const { deleted, errors } = (await api.create(`api/projects/${currentProjectId}/insights/bulk_delete/`, {
                ids: Array.from(selectedIds),
            })) as BulkDeleteInsightsResult
            if (errors.length === 0) {
                lemonToast.success(`Deleted ${deleted.length} insight${deleted.length !== 1 ? 's' : ''}`)
            } else {
                lemonToast.warning(
                    `Deleted ${deleted.length} insight${deleted.length !== 1 ? 's' : ''}. ${errors.length} skipped (not found or no permission).`
                )
            }
            onSuccess?.()
        } catch {
            lemonToast.error('Failed to delete insights')
        } finally {
            setLoading(false)
        }
    }

    return (
        <LemonButton
            type="secondary"
            status="danger"
            size="small"
            icon={<IconTrash />}
            loading={loading}
            onClick={() => {
                LemonDialog.open({
                    title: `Delete ${count} insight${plural}?`,
                    description: `Are you sure you want to delete ${count} insight${plural}? Deleted insights can be restored from each insight's history.`,
                    primaryButton: {
                        children: 'Delete',
                        status: 'danger',
                        onClick: () => void submit(),
                    },
                    secondaryButton: {
                        children: 'Cancel',
                    },
                })
            }}
        >
            {loading ? 'Deleting…' : 'Delete insights'}
        </LemonButton>
    )
}
