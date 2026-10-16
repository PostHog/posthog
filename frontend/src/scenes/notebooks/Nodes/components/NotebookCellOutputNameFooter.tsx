import clsx from 'clsx'
import { ReactNode } from 'react'

import { IconCornerDownRight } from '@posthog/icons'

import { useComponentPanelState } from 'lib/components/MarkdownNotebook/componentPanelContext'
import { useNotebookJupyterCommands } from 'lib/components/MarkdownNotebook/jupyterMode'

/** The bar under a code cell's output that names the dataframe the cell binds. Shared by the SQL
 * and Python cells, which differ only in what they put after the input. */
export function NotebookCellOutputNameFooter({
    returnVariable,
    onChange,
    inputRef,
    children,
}: {
    returnVariable: string
    onChange: (returnVariable: string) => void
    /** Receives the input element, for a caller that anchors something to it. */
    inputRef?: (element: HTMLInputElement | null) => void
    /** Drawn after the input: a validation error, usage links, a hint. */
    children?: ReactNode
}): JSX.Element | null {
    const componentPanelState = useComponentPanelState()
    const isJupyterMode = !!useNotebookJupyterCommands()

    if (componentPanelState && !componentPanelState.showEditPanel) {
        return null
    }

    return (
        <div
            // Translucent overlay, not a surface token: the shell is surface-primary in light
            // mode but surface-tertiary in dark, so a fixed surface vanishes against one of them.
            className={clsx(
                'flex shrink-0 flex-wrap items-center gap-2 text-muted border-t border-primary bg-fill-highlight-50',
                isJupyterMode ? 'px-2 py-1 text-xxs' : 'p-2 text-xs'
            )}
            onClick={(event) => event.stopPropagation()}
            onMouseDown={(event) => event.stopPropagation()}
        >
            <span className="font-mono mt-0.5">
                <IconCornerDownRight />
            </span>
            <input
                type="text"
                // The dataframe name this cell's result is exposed as to later cells. A SQL cell
                // references it as a table name (`from sql_df`), a Python cell as a variable.
                // Optional: left empty, the cell exports nothing and later cells can't read it.
                className={clsx(
                    'max-w-full rounded border border-primary px-1.5 py-0.5 font-mono bg-surface-primary focus:outline-none focus:ring-1 focus:ring-primary',
                    isJupyterMode
                        ? 'w-44 text-xxs text-secondary'
                        : 'w-56 text-sm font-medium text-[oklch(0.27_0.022_345deg)] dark:text-[oklch(0.93_0.014_345deg)]'
                )}
                value={returnVariable}
                onChange={(event) => onChange(event.target.value)}
                placeholder="Output dataframe name"
                aria-label="Output dataframe name"
                spellCheck={false}
                ref={inputRef}
            />
            {children}
        </div>
    )
}
