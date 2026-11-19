import { PANE_LEFT, PANE_RIGHT, PANE_ROW } from './paneClasses'

/** The column names of a repository list. Narrow, the cells stack, so the names are hidden. */
export function RepositoryColumnHeaders({
    columns,
}: {
    columns: { label: string; pane: 'left' | 'right' }[]
}): JSX.Element {
    return (
        <>
            {columns.map(({ label, pane }) => (
                <div
                    key={label}
                    className={`hidden px-4 py-1.5 text-xxs font-semibold tracking-wide text-secondary uppercase @min-[48rem]:block ${pane === 'right' ? PANE_RIGHT : PANE_LEFT} ${PANE_ROW}`}
                >
                    {label}
                </div>
            ))}
        </>
    )
}
