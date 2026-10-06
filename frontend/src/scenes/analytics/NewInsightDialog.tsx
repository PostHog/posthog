import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { NewInsightMenuContent } from 'scenes/saved-insights/NewInsightMenu'

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
        router.actions.push(withBackLink(href))
    }

    return (
        <LemonModal
            isOpen={newInsightDialogOpen}
            onClose={() => setNewInsightDialogOpen(false)}
            title="New insight"
            width="min(60rem, calc(100vw - 2rem))"
            data-attr="analytics-new-insight-dialog"
        >
            <div onClickCapture={onClickCapture}>
                <NewInsightMenuContent />
            </div>
        </LemonModal>
    )
}
