import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { Dialog, DialogBody, DialogContent, DialogHeader, DialogTitle } from '@posthog/quill'

import { NewInsightMenuContent } from 'products/product_analytics/frontend/insights/newInsightMenu/NewInsightMenu'

import { withBackLink } from './analyticsBackLink'
import { newAnalyticsLogic } from './newAnalyticsLogic'

/** The insight type picker in a dialog, so the Analytics pages stay put until a type is chosen. */
export function NewInsightDialog(): JSX.Element {
    const { newInsightDialogOpen } = useValues(newAnalyticsLogic)
    const { setNewInsightDialogOpen } = useActions(newAnalyticsLogic)

    // The picker's cards are plain links to the editor. Catching the click here adds the way back to
    // Analytics, which the editor then carries on to the saved insight.
    const onClickCapture = (event: React.MouseEvent<HTMLDivElement>): void => {
        const anchor = (event.target as HTMLElement).closest('a[href]')
        if (!anchor || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) {
            return
        }
        event.preventDefault()
        event.stopPropagation()
        const href = anchor.getAttribute('href') ?? ''
        setNewInsightDialogOpen(false)
        router.actions.push(withBackLink(href))
    }

    return (
        <Dialog open={newInsightDialogOpen} onOpenChange={(open: boolean) => !open && setNewInsightDialogOpen(false)}>
            <DialogContent size="wide" data-attr="analytics-new-insight-dialog">
                <DialogHeader>
                    <DialogTitle>New insight</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div onClickCapture={onClickCapture}>
                        <NewInsightMenuContent />
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
