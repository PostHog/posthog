import { ReactNode } from 'react'

import { IconCornerDownRight } from '@posthog/icons'

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
}): JSX.Element {
    return (
        <div
            // Translucent overlay, not a surface token: the shell is surface-primary in light
            // mode but surface-tertiary in dark, so a fixed surface vanishes against one of them.
            className="flex shrink-0 items-center gap-2 text-xs text-muted border-t border-primary bg-fill-highlight-50 p-2"
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
                // Wide enough for the placeholder to sit on one line without clipping. The name
                // carries weight through size and a faintly warm near-black rather than a hue,
                // because a saturated color here competes with the accent the app spends on links.
                className="w-56 rounded border border-primary px-1.5 py-0.5 text-sm font-medium font-mono bg-surface-primary text-[oklch(0.27_0.022_345deg)] dark:text-[oklch(0.93_0.014_345deg)] focus:outline-none focus:ring-1 focus:ring-primary"
                value={returnVariable}
                onChange={(event) => onChange(event.target.value)}
                placeholder="Output dataframe name"
                spellCheck={false}
                ref={inputRef}
            />
            {children}
        </div>
    )
}
