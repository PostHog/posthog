import type { NotebookComponentRenderProps } from './types'

export function NotebookColumnBoundary({ node }: NotebookComponentRenderProps): JSX.Element {
    return (
        <p className="text-muted">
            <span>{`Unmatched ${node.tagName.replace('End', ' closing')} boundary. `}</span>
            <span>
                Use Markdown source to pair Columns and Column tags. Content is shown at full width until the layout is
                complete.
            </span>
        </p>
    )
}
