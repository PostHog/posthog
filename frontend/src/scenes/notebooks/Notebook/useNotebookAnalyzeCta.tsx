import { BuiltLogic, useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconSparkles } from '@posthog/icons'

import type { NotebookComponentToolbarCta } from 'lib/components/MarkdownNotebook/componentToolbarExtras'

import { NotebookNodeType } from '../types'
import { NotebookAnalyzeCellAttributes, getNotebookAnalyzeCell } from './notebookAnalyzeContext'
import { notebookAnalyzeLogic } from './notebookAnalyzeLogic'
import type { notebookLogicType } from './notebookLogic'

/**
 * The cell header's "Explore more" button, or null when the cell or the notebook is not eligible. It
 * sits in the header rather than the menu, because analysis reads the cell and a reader in view mode
 * is exactly who wants it.
 */
export function useNotebookAnalyzeCta(
    notebookLogic: BuiltLogic<notebookLogicType>,
    nodeType: NotebookNodeType,
    attributes: NotebookAnalyzeCellAttributes
): NotebookComponentToolbarCta | null {
    const logicProps = useMemo(() => ({ notebookLogic }), [notebookLogic])
    const logic = notebookAnalyzeLogic(logicProps)
    const { analyzeEnabled } = useValues(logic)
    const { startAnalysis } = useActions(logic)

    const cell = useMemo(
        () => getNotebookAnalyzeCell(nodeType, attributes, notebookLogic.props.shortId),
        [nodeType, attributes, notebookLogic.props.shortId]
    )

    return useMemo(
        () =>
            analyzeEnabled && cell
                ? {
                      label: 'Explore more',
                      icon: <IconSparkles />,
                      tooltip: 'Analyze this cell with PostHog AI',
                      // pinned: data-attr value, renaming it breaks autocapture dashboards
                      dataAttr: 'notebook-analyze-more',
                      onClick: () => startAnalysis(cell),
                  }
                : null,
        [analyzeEnabled, cell, startAnalysis]
    )
}
