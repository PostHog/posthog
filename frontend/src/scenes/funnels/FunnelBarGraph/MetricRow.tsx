export function MetricRow({ title, value }: { title: string; value: string | number }): JSX.Element {
    return (
        <div style={{ width: '100%', display: 'flex', justifyContent: 'space-between' }}>
            <div>{title}</div>
            <div>
                <strong style={{ paddingLeft: 6 }}>{value}</strong>
            </div>
        </div>
    )
}
