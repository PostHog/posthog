export function MetricRow({ title, value }: { title: string; value: string | number }): JSX.Element {
    return (
        <div className="flex justify-between w-full">
            <div>{title}</div>
            <div>
                <strong style={{ paddingLeft: 6 }}>{value}</strong>
            </div>
        </div>
    )
}
