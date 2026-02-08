import { LemonDialog } from '@posthog/lemon-ui'

import { ProductTour } from '~/types'

import { isProductTourRunning } from './productToursLogic'

export function openDeleteProductTourDialog(
    tour: Pick<ProductTour, 'start_date'>,
    onConfirm: () => void
): void {
    const isDraft = !tour.start_date
    LemonDialog.open({
        title: 'Permanently delete this product tour?',
        content: isDraft ? (
            <div className="text-sm text-secondary">
                <strong>This action cannot be undone.</strong>
            </div>
        ) : (
            <div className="text-sm text-secondary">
                <p>
                    <strong>This action cannot be undone.</strong>
                </p>
                <p className="mt-2">The tour configuration will be permanently deleted.</p>
                <p className="mt-2 text-muted">Note: Tour interaction events in your data will not be affected.</p>
            </div>
        ),
        primaryButton: {
            children: 'Delete permanently',
            type: 'primary',
            status: 'danger',
            onClick: onConfirm,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

export function openArchiveProductTourDialog(
    tour: Pick<ProductTour, 'start_date' | 'end_date'>,
    onConfirm: () => void
): void {
    const isRunning = isProductTourRunning(tour)
    LemonDialog.open({
        title: 'Archive this product tour?',
        content: isRunning ? (
            <div className="text-sm text-secondary">
                <p>This tour is currently running. Archiving will:</p>
                <ul className="list-disc ml-4 mt-2">
                    <li>Stop the tour immediately</li>
                    <li>Remove it from your active tours list</li>
                </ul>
                <p className="mt-2">You can restore this tour at any time from the Archived tab.</p>
            </div>
        ) : (
            <div className="text-sm text-secondary">
                This will remove the tour from your active tours list. You can restore it at any time from the Archived
                tab.
            </div>
        ),
        primaryButton: {
            children: isRunning ? 'Stop and archive' : 'Archive',
            type: 'primary',
            onClick: onConfirm,
            size: 'small',
        },
        secondaryButton: {
            children: 'Cancel',
            type: 'tertiary',
            size: 'small',
        },
    })
}

export function canDeleteProductTour(tour: Pick<ProductTour, 'archived' | 'start_date'>): boolean {
    return tour.archived || !tour.start_date
}
