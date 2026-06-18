import { LemonModal, Spinner } from '@posthog/lemon-ui'

import { MaterializationStatusPanel } from './MaterializationStatusPanel'

type MaterializationStatusModalKind = 'view' | 'endpoint'

interface MaterializationStatusModalProps {
    isOpen: boolean
    onClose: () => void
    viewId: string | null
    viewName?: string
    kind?: MaterializationStatusModalKind
}

function buildTitle(kind: MaterializationStatusModalKind, viewName: string | undefined): string {
    return viewName ? `Materialize ${kind} ${viewName}` : `Materialize ${kind}`
}

export function MaterializationStatusModal({
    isOpen,
    onClose,
    viewId,
    viewName,
    kind = 'view',
}: MaterializationStatusModalProps): JSX.Element {
    return (
        <LemonModal title={buildTitle(kind, viewName)} isOpen={isOpen} onClose={onClose} width={960}>
            <div className="max-h-[75vh] overflow-auto">
                {viewId ? (
                    <MaterializationStatusPanel viewId={viewId} kind={kind} />
                ) : (
                    <div className="flex min-h-64 items-center justify-center">
                        <Spinner className="text-2xl" />
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
