import clsx from 'clsx'

/** Shown by the line, bar, and combo SQL charts when there is no series to draw, so the surface
 *  says why instead of leaving an empty box. Pie and scatter carry their own wording because the
 *  action they ask for is different. */
export const SqlChartNothingToPlot = ({ className }: { className?: string }): JSX.Element => {
    return (
        <div className={clsx(className, 'rounded bg-surface-primary flex flex-1 items-center justify-center p-6')}>
            <span className="text-secondary text-sm">
                No values to plot. Pick a numeric column for the Y axis, and check that the query returns rows.
            </span>
        </div>
    )
}
