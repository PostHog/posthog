import { type CSSProperties, type ReactNode, useRef, useState } from 'react'

import { IconColumns } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, Popover } from '@posthog/lemon-ui'

import { getColumnWidth, NotebookColumnsGroup } from './columnLayout'
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
    const [settingsOpen, setSettingsOpen] = useState(false)
    const toolbarRef = useRef<HTMLDivElement>(null)
    const widths = group.columns.map((column) => getColumnWidth(column.start.node.props))
    return (
        <section className="MarkdownNotebook__columns" aria-label="Notebook columns">
            {mode === 'edit' && (
                <div className="MarkdownNotebook__columns-toolbar" contentEditable={false} ref={toolbarRef}>
                    <Popover
                        visible={settingsOpen}
                        additionalRefs={[toolbarRef]}
                        onClickOutside={() => setSettingsOpen(false)}
                        placement="bottom-end"
                        overlay={
                            <div
                                className="MarkdownNotebook__columns-settings"
                                contentEditable={false}
                                onKeyDown={(event) => {
                                    if (event.key === 'Escape') {
                                        setSettingsOpen(false)
                                    }
                                }}
                            >
                                <span className="font-semibold">Column layout</span>
                                <LemonSegmentedButton
                                    size="small"
                                    fullWidth
                                    value={group.columns.length}
                                    options={[2, 3, 4].map((count) => ({
                                        value: count,
                                        label: `${count} columns`,
                                        'data-attr': `notebook-columns-count-${count}`,
                                    }))}
                                    onChange={onCountChange}
                                />
                                <div className="flex items-center justify-between">
                                    <span className="font-semibold">Relative widths</span>
                                    <LemonButton
                                        size="xsmall"
                                        onClick={() => onWidthsChange(widths.map(() => 1))}
                                        data-attr="notebook-columns-equal-widths"
                                    >
                                        Equal widths
                                    </LemonButton>
                                </div>
                                {group.columns.map((column, index) => (
                                    <label className="MarkdownNotebook__column-width" key={column.start.key}>
                                        <span>{`Column ${index + 1}`}</span>
                                        <input
                                            type="range"
                                            min={1}
                                            max={12}
                                            step={1}
                                            value={widths[index]}
                                            aria-label={`Column ${index + 1} width`}
                                            data-attr="notebook-column-width"
                                            onChange={(event) =>
                                                onWidthsChange(
                                                    widths.map((current, i) =>
                                                        i === index ? Number(event.target.value) : current
                                                    )
                                                )
                                            }
                                        />
                                        <span className="tabular-nums text-right">{`${widths[index]}×`}</span>
                                    </label>
                                ))}
                                <p className="text-xs text-secondary m-0">
                                    Removing columns keeps their content in the last column.
                                </p>
                                <div className="border-t pt-2">
                                    <LemonButton
                                        size="small"
                                        fullWidth
                                        onClick={onRemoveLayout}
                                        data-attr="notebook-columns-remove"
                                    >
                                        Remove layout, keep content
                                    </LemonButton>
                                </div>
                            </div>
                        }
                    >
                        <LemonButton
                            size="xsmall"
                            icon={<IconColumns />}
                            onClick={() => setSettingsOpen(!settingsOpen)}
                            active={settingsOpen}
                            aria-expanded={settingsOpen}
                            aria-label="Configure columns"
                            data-attr="notebook-columns-count"
                        >
                            {`${group.columns.length} columns`}
                        </LemonButton>
                    </Popover>
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
                {group.columns.map((column) => (
                    <div className="MarkdownNotebook__column" key={column.start.key}>
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
