import clsx from 'clsx'
import { ReactNode } from 'react'

import { useComponentPanelState } from 'lib/components/MarkdownNotebook/componentPanelContext'

import type { NotebookNodeSQLV2Result } from '../NotebookNodeSQLV2'
import { NotebookDataframeResult } from '../pythonExecution'
import { NotebookJupyterDataframe, NotebookJupyterDataframeProps } from './NotebookJupyterDataframe'

export type NotebookJupyterCellOutputProps = {
    result: NotebookNodeSQLV2Result | null
    dataframeResult: NotebookDataframeResult | null
    dataframeProps: Omit<NotebookJupyterDataframeProps, 'result' | 'totalRowCount'>
    runError: string | null
    status: string | null
    executionCount: number | null
    returnVariable: string
    onReturnVariableChange: (returnVariable: string) => void
    isEditable: boolean
    valueOverride?: ReactNode
    footerExtra?: ReactNode
}

function OutputRow({
    prompt,
    className,
    children,
}: {
    prompt?: ReactNode
    className?: string
    children: ReactNode
}): JSX.Element {
    return (
        <div className="MarkdownNotebook__jupyter-output-row">
            <div className="MarkdownNotebook__jupyter-prompt MarkdownNotebook__jupyter-prompt--output">{prompt}</div>
            <div className={clsx('MarkdownNotebook__jupyter-output-area', className)}>{children}</div>
        </div>
    )
}

/**
 * A code cell's output area in Jupyter mode: printed streams first, then the cell's value under an
 * `Out[n]:` prompt, the way Jupyter orders stream, display, and execute-result outputs.
 */
export function NotebookJupyterCellOutput({
    result,
    dataframeResult,
    dataframeProps,
    runError,
    status,
    executionCount,
    returnVariable,
    onReturnVariableChange,
    isEditable,
    valueOverride,
    footerExtra,
}: NotebookJupyterCellOutputProps): JSX.Element | null {
    const interactivePrompt = useComponentPanelState()?.jupyterOutputPrompt
    const outPrompt = interactivePrompt?.(false) ?? <span>{`Out[${executionCount ?? ' '}]:`}</span>
    const errPrompt = interactivePrompt?.(true) ?? <span>{`Err[${executionCount ?? ' '}]:`}</span>
    const media = result?.media ?? []
    const firstPageLength = result?.first_page?.length ?? 0
    // The kernel's row_count is the page size for a paged frame, so it only counts as the total
    // once the whole frame fits on the first page.
    const totalRowCount = result && !result.has_more && result.row_count >= firstPageLength ? result.row_count : null
    const resultText = !dataframeResult && !runError ? result?.result_text : undefined
    const hasValue = !!dataframeResult || media.length > 0 || !!resultText
    const hasValueRow = !!resultText || (!!dataframeResult && !runError)
    const leadingPrompt = interactivePrompt && !hasValueRow ? { prompt: outPrompt } : {}

    if (!status && !result?.stdout && !result?.stderr && !runError && !hasValue) {
        return interactivePrompt ? <OutputRow prompt={outPrompt}>{null}</OutputRow> : null
    }

    return (
        <div className="py-0.5" onClick={(event) => event.stopPropagation()}>
            {status ? (
                <OutputRow {...leadingPrompt} className="MarkdownNotebook__jupyter-output-area--muted">
                    {status}
                </OutputRow>
            ) : null}
            {result?.stdout ? (
                <OutputRow {...(!status ? leadingPrompt : {})}>
                    <pre>{result.stdout}</pre>
                </OutputRow>
            ) : null}
            {result?.stderr ? (
                <OutputRow
                    {...(!status && !result?.stdout && !hasValueRow ? { prompt: errPrompt } : {})}
                    className="MarkdownNotebook__jupyter-output-area--stderr"
                >
                    <pre>{result.stderr}</pre>
                </OutputRow>
            ) : null}
            {runError ? (
                <OutputRow
                    {...(!status && !result?.stdout && !result?.stderr && !hasValueRow ? { prompt: errPrompt } : {})}
                    className="MarkdownNotebook__jupyter-output-area--error"
                >
                    <pre>{runError}</pre>
                </OutputRow>
            ) : null}
            {media.map((item, index) => (
                <OutputRow
                    key={index}
                    {...(index === 0 && !status && !result?.stdout && !result?.stderr && !runError
                        ? leadingPrompt
                        : {})}
                >
                    <img src={`data:${item.mime_type};base64,${item.data}`} alt="Cell output" />
                </OutputRow>
            ))}
            {resultText ? (
                <OutputRow prompt={outPrompt}>
                    <pre>{resultText}</pre>
                </OutputRow>
            ) : null}
            {dataframeResult && !runError ? (
                <OutputRow prompt={outPrompt}>
                    {valueOverride ?? (
                        <NotebookJupyterDataframe
                            {...dataframeProps}
                            result={dataframeResult}
                            totalRowCount={totalRowCount}
                        />
                    )}
                </OutputRow>
            ) : null}
            {dataframeResult && isEditable ? (
                <OutputRow className="MarkdownNotebook__jupyter-output-area--muted flex flex-wrap items-center gap-3">
                    <label className="flex items-center gap-1.5 text-xxs">
                        <span>Saved as</span>
                        <input
                            type="text"
                            className="w-44 px-1 text-xxs font-mono bg-transparent rounded border border-transparent hover:border-primary focus:border-primary focus:outline-none text-secondary"
                            value={returnVariable}
                            onChange={(event) => onReturnVariableChange(event.target.value)}
                            placeholder="Output dataframe name"
                            aria-label="Output dataframe name"
                            spellCheck={false}
                        />
                    </label>
                    {footerExtra}
                </OutputRow>
            ) : null}
        </div>
    )
}
