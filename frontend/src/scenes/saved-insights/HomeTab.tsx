import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { NotebookLoadingState } from 'scenes/notebooks/Notebook/NotebookLoadingState'

import { productAnalyticsHomeLogic } from './productAnalyticsHomeLogic'

export function HomeTab(): JSX.Element {
    const { homeNotebook, homeNotebookLoading, homeNotebookError } = useValues(productAnalyticsHomeLogic)
    const { loadHomeNotebook } = useActions(productAnalyticsHomeLogic)

    if (homeNotebookLoading || (!homeNotebook && !homeNotebookError)) {
        return <NotebookLoadingState />
    }

    if (homeNotebookError) {
        return (
            <LemonBanner
                type="error"
                className="my-4"
                action={{
                    children: 'Try again',
                    loading: homeNotebookLoading,
                    onClick: () => loadHomeNotebook(),
                    'data-attr': 'product-analytics-home-notebook-retry',
                }}
            >
                We could not load the shared product analytics notebook.
            </LemonBanner>
        )
    }

    if (!homeNotebook) {
        return <NotebookLoadingState />
    }

    return <Notebook shortId={homeNotebook.short_id} mode="notebook" className="py-4" />
}
