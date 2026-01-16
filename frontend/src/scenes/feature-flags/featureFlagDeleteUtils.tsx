import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonCheckbox, LemonModal } from '@posthog/lemon-ui'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { FeatureFlagType } from '~/types'

function DeleteFeatureFlagModal({
    featureFlag,
    currentTeamId,
    isOpen,
    onClose,
    onDelete,
}: {
    featureFlag: Pick<FeatureFlagType, 'key' | 'id' | 'usage_dashboard'>
    currentTeamId: number
    isOpen: boolean
    onClose: () => void
    onDelete: () => void
}): JSX.Element {
    const [deleteUsageDashboard, setDeleteUsageDashboard] = useState(false)
    const [isDeleting, setIsDeleting] = useState(false)

    // Reset checkbox state when modal opens for a different flag
    useEffect(() => {
        if (isOpen) {
            setDeleteUsageDashboard(false)
        }
    }, [isOpen, featureFlag.id])

    const handleDelete = async (): Promise<void> => {
        setIsDeleting(true)
        try {
            if (deleteUsageDashboard && featureFlag.usage_dashboard) {
                await api.update(`environments/${currentTeamId}/dashboards/${featureFlag.usage_dashboard}`, {
                    deleted: true,
                    delete_insights: true,
                })
            }
            onDelete()
            onClose()
        } catch {
            lemonToast.error('Failed to delete dashboard. Please try again.')
        } finally {
            setIsDeleting(false)
        }
    }

    return (
        <LemonModal
            title="Delete feature flag?"
            isOpen={isOpen}
            onClose={onClose}
            footer={
                <>
                    <div className="flex-1">
                        {featureFlag.usage_dashboard && (
                            <LemonCheckbox
                                checked={deleteUsageDashboard}
                                onChange={setDeleteUsageDashboard}
                                label="Also delete flag usage dashboard"
                                labelClassName="font-normal"
                                data-attr="delete-usage-dashboard-checkbox"
                            />
                        )}
                    </div>
                    <LemonButton type="secondary" onClick={onClose} disabled={isDeleting}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="secondary" status="danger" onClick={handleDelete} loading={isDeleting}>
                        Delete
                    </LemonButton>
                </>
            }
        >
            Are you sure you want to delete "{featureFlag.key}"?
        </LemonModal>
    )
}

export function useDeleteFeatureFlagModal({ currentTeamId }: { currentTeamId: number }): {
    DeleteFeatureFlagModal: JSX.Element | null
    openDeleteModal: (
        featureFlag: Pick<FeatureFlagType, 'key' | 'id' | 'usage_dashboard'>,
        onDelete: () => void
    ) => void
} {
    const [isOpen, setIsOpen] = useState(false)
    const [featureFlag, setFeatureFlag] = useState<Pick<FeatureFlagType, 'key' | 'id' | 'usage_dashboard'> | null>(null)
    const onDeleteRef = useRef<(() => void) | null>(null)

    const openDeleteModal = (
        flag: Pick<FeatureFlagType, 'key' | 'id' | 'usage_dashboard'>,
        onDelete: () => void
    ): void => {
        setFeatureFlag(flag)
        onDeleteRef.current = onDelete
        setIsOpen(true)
    }

    const modal = featureFlag ? (
        <DeleteFeatureFlagModal
            featureFlag={featureFlag}
            currentTeamId={currentTeamId}
            isOpen={isOpen}
            onClose={() => setIsOpen(false)}
            onDelete={() => onDeleteRef.current?.()}
        />
    ) : null

    return { DeleteFeatureFlagModal: modal, openDeleteModal }
}
