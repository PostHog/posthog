import { IconCheckCircle, IconCircleDashed } from '@posthog/icons'
import { Badge, Spinner } from '@posthog/quill'

import { ProductTour, ProgressStatus } from '~/types'

import { getProductTourStatus } from '../productToursLogic'

const STATUS_CONFIG: Record<ProgressStatus, { label: string; variant: 'success' | 'default' | 'completed' }> = {
    [ProgressStatus.Draft]: { label: 'Draft', variant: 'default' },
    [ProgressStatus.Running]: { label: 'Running', variant: 'success' },
    [ProgressStatus.Complete]: { label: 'Complete', variant: 'completed' },
}

export function QuillProductTourStatusBadge({
    tour,
    isEditing,
    draftSaveStatus,
}: {
    tour: ProductTour
    isEditing?: boolean
    draftSaveStatus?: 'unsaved' | 'saving' | 'saved' | null
}): JSX.Element {
    const config = STATUS_CONFIG[getProductTourStatus(tour)]
    return (
        <Badge variant={config.variant}>
            {isEditing && (
                <>
                    {draftSaveStatus === 'unsaved' && <IconCircleDashed />}
                    {draftSaveStatus === 'saving' && <Spinner />}
                    {draftSaveStatus === 'saved' && <IconCheckCircle className="text-success" />}
                </>
            )}
            {config.label}
        </Badge>
    )
}
