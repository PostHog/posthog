import { BuiltLogic, useActions, useValues } from 'kea'
import { useMemo } from 'react'

import type { LemonMenuItem } from '@posthog/lemon-ui'

import { NotebookNodeType } from '../types'
import { NotebookAnalyzeCellAttributes, getNotebookAnalyzeCell } from './notebookAnalyzeContext'
import { notebookAnalyzeLogic } from './notebookAnalyzeLogic'
import type { notebookLogicType } from './notebookLogic'

/**
 * The cell menu's "Analyze with PostHog AI" entry, or null when the cell or the notebook is not
 * eligible. It goes in `menuItems` rather than the edit-mode actions, because analysis reads the
 * cell and a reader in view mode is exactly who wants it.
 */
export function useNotebookAnalyzeMenuItem(
    notebookLogic: BuiltLogic<notebookLogicType>,
    nodeType: NotebookNodeType,
    attributes: NotebookAnalyzeCellAttributes
): LemonMenuItem | null {
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
                      label: 'Analyze with PostHog AI',
                      'data-attr': 'notebook-analyze-more',
                      onClick: () => startAnalysis(cell),
                  }
                : null,
        [analyzeEnabled, cell, startAnalysis]
    )
}
