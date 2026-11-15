import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { ProductTour, ProgressStatus } from '~/types'

import { productTourDialogHandlers } from './productTourDialogHandlers'
import { productTourLogic } from './productTourLogic'
import { getProductTourStatus, isProductTourRunning } from './productToursLogic'

export function QuillProductTourViewActions({
    id,
    productTour,
}: {
    id: string
    productTour: ProductTour
}): JSX.Element {
    const { launchValidationIssues } = useValues(productTourLogic({ id }))
    const { editingProductTour, launchProductTour, stopProductTour, resumeProductTour, openToolbarModal } = useActions(
        productTourLogic({ id })
    )

    const { handleLaunch, handleStop, handleResume } = productTourDialogHandlers({
        launchValidationIssues,
        editingProductTour,
        launchProductTour,
        stopProductTour,
        resumeProductTour,
    })

    const status = getProductTourStatus(productTour)
    const isRunning = isProductTourRunning(productTour)

    return (
        <>
            <Button variant="outline" onClick={() => openToolbarModal('preview')}>
                Preview
            </Button>
            <Button variant="outline" onClick={() => editingProductTour(true)}>
                Edit
            </Button>
            {status === ProgressStatus.Draft && (
                <Button variant="primary" onClick={handleLaunch}>
                    Launch
                </Button>
            )}
            {isRunning && (
                <Button variant="destructive-outline" onClick={handleStop}>
                    Stop
                </Button>
            )}
            {status === ProgressStatus.Complete && !productTour.archived && (
                <Button variant="outline" onClick={handleResume}>
                    Resume
                </Button>
            )}
        </>
    )
}
