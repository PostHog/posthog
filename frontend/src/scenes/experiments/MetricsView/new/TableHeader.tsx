interface TableHeaderProps {
    variants: string[]
}

export function TableHeader({ variants }: TableHeaderProps): JSX.Element {
    // Find baseline (control) and test variants
    const baseline = variants.find((v) => v === 'control') || variants[0]
    const testVariants = variants.filter((v) => v !== baseline)

    return (
        <thead>
            <tr>
                <th className="metric-header">Metric</th>
                <th className="baseline-header">{baseline}</th>
                <th className="variant-header">{testVariants.length === 1 ? testVariants[0] : 'Variants'}</th>
                <th className="chart-header">Chart</th>
            </tr>
        </thead>
    )
}
