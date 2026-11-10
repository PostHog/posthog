import type { CSSProperties, ReactNode } from 'react'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { getColumnWidths, NotebookColumnsGroup } from './columnLayout'
import type { MarkdownNotebookVisualGroup } from './documentModel'
import type { NotebookMode } from './types'

export function NotebookColumns({
    group,
    mode,
    renderGroup,
    onCountChange,
    onWidthsChange,
    onRemoveLayout,
    onAddBlock,
}: {
    group: NotebookColumnsGroup
    mode: NotebookMode
    renderGroup: (group: MarkdownNotebookVisualGroup) => ReactNode
    onCountChange: (count: number) => void
    onWidthsChange: (widths: number[]) => void
    onRemoveLayout: () => void
    onAddBlock: (boundaryIndex: number) => void
}): JSX.Element {
    const widths = getColumnWidths(group.start.node.props, group.columns.length)
    return (
        <section className="MarkdownNotebook__columns" aria-label="Notebook columns">
            {mode === 'edit' && (
                <div className="MarkdownNotebook__columns-toolbar" contentEditable={false}>
                    <LemonSelect
                        size="small"
                        value={group.columns.length}
                        options={[2, 3, 4].map((count) => ({ value: count, label: `${count} columns` }))}
                        onChange={onCountChange}
                        aria-label="Number of columns"
                        data-attr="notebook-columns-count"
                        tooltip="Reducing the number of columns moves their content into the last remaining column."
                    />
                    <LemonButton
                        size="small"
                        onClick={() => onWidthsChange(widths.map(() => 1))}
                        data-attr="notebook-columns-equal-widths"
                    >
                        Equal widths
                    </LemonButton>
                    <LemonButton size="small" onClick={onRemoveLayout} data-attr="notebook-columns-remove">
                        Remove layout
                    </LemonButton>
                </div>
            )}
            <div
                className="MarkdownNotebook__columns-grid"
                style={
                    {
                        '--notebook-column-tracks': widths.map((width) => `minmax(0, ${width}fr)`).join(' '),
                    } as CSSProperties
                }
            >
                {group.columns.map((column, index) => (
                    <div className="MarkdownNotebook__column" key={column.start.key}>
                        {mode === 'edit' && (
                            <div className="MarkdownNotebook__column-toolbar" contentEditable={false}>
                                <span>{`Column ${index + 1}`}</span>
                                <LemonSelect
                                    size="xsmall"
                                    value={widths[index]}
                                    options={[1, 2, 3, 4].map((width) => ({ value: width, label: `${width}× width` }))}
                                    onChange={(width) =>
                                        onWidthsChange(widths.map((current, i) => (i === index ? width : current)))
                                    }
                                    aria-label={`Column ${index + 1} width`}
                                    data-attr="notebook-column-width"
                                />
                            </div>
                        )}
                        {column.groups.map(renderGroup)}
                        {mode === 'edit' && column.groups.length === 0 && (
                            <div contentEditable={false}>
                                <LemonButton
                                    size="small"
                                    onClick={() => onAddBlock(column.end.index)}
                                    data-attr="notebook-column-add-block"
                                >
                                    Add text or chart
                                </LemonButton>
                            </div>
                        )}
                    </div>
                ))}
            </div>
        </section>
    )
}
