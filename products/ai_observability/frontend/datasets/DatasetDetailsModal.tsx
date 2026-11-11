import { LemonModal } from '@posthog/lemon-ui'

import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { isObject } from 'lib/utils/guards'

import type { DatasetReadApi } from '../generated/api.schemas'

export function DatasetDetailsModal({
    dataset,
    isOpen,
    onClose,
}: {
    dataset: DatasetReadApi
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    return (
        <LemonModal title="Dataset details" isOpen={isOpen} onClose={onClose} width="40rem">
            <div className="flex flex-col gap-4">
                <div>
                    <h4 className="mb-1">Name</h4>
                    <p className="m-0 break-words">{dataset.name}</p>
                </div>
                {dataset.description && (
                    <div>
                        <h4 className="mb-1">Description</h4>
                        <p className="m-0 break-words">{dataset.description}</p>
                    </div>
                )}
                <div>
                    <h4 className="mb-1">Metadata</h4>
                    {isObject(dataset.metadata) && Object.keys(dataset.metadata).length > 0 ? (
                        <div className="overflow-x-auto">
                            <HighlightedJSONViewer src={dataset.metadata} />
                        </div>
                    ) : (
                        <p className="text-muted m-0">No metadata.</p>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
