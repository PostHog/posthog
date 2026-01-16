import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonCheckbox, LemonModal } from '@posthog/lemon-ui'

import { FeatureFlagType } from '~/types'

function DeleteFeatureFlagModal({
    featureFlag,
    isOpen,
    onClose,
    onDelete,
}: {
    featureFlag: Pick<FeatureFlagType, 'key' | 'id' | 'usage_dashboard'>
    isOpen: boolean
    onClose: () => void
    onDelete: (deleteUsageDashboard: boolean) => void
}): JSX.Element {
    const [deleteUsageDashboard, setDeleteUsageDashboard] = useState(false)

    // Reset checkbox state when modal opens for a different flag
    useEffect(() => {
        if (isOpen) {
            setDeleteUsageDashboard(false)
        }
    }, [isOpen, featureFlag.id])

    const handleDelete = (): void => {
        onDelete(deleteUsageDashboard)
        onClose()
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
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="secondary" status="danger" onClick={handleDelete}>
                        Delete
                    </LemonButton>
                </>
            }
        >
            Are you sure you want to delete "{featureFlag.key}"?
        </LemonModal>
    )
}

export function useDeleteFeatureFlagModal(): {
    DeleteFeatureFlagModal: JSX.Element | null
    openDeleteModal: (
        featureFlag: Pick<FeatureFlagType, 'key' | 'id' | 'usage_dashboard'>,
        onDelete: (deleteUsageDashboard: boolean) => void
    ) => void
} {
    const [isOpen, setIsOpen] = useState(false)
    const [featureFlag, setFeatureFlag] = useState<Pick<FeatureFlagType, 'key' | 'id' | 'usage_dashboard'> | null>(null)
    const onDeleteRef = useRef<((deleteUsageDashboard: boolean) => void) | null>(null)

    const openDeleteModal = (
        flag: Pick<FeatureFlagType, 'key' | 'id' | 'usage_dashboard'>,
        onDelete: (deleteUsageDashboard: boolean) => void
    ): void => {
        setFeatureFlag(flag)
        onDeleteRef.current = onDelete
        setIsOpen(true)
    }

    const modal = featureFlag ? (
        <DeleteFeatureFlagModal
            featureFlag={featureFlag}
            isOpen={isOpen}
            onClose={() => setIsOpen(false)}
            onDelete={(deleteUsageDashboard) => onDeleteRef.current?.(deleteUsageDashboard)}
        />
    ) : null

    return { DeleteFeatureFlagModal: modal, openDeleteModal }
}
