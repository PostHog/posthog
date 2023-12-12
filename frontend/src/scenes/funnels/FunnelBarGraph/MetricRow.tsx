export function MetricRow({ title, value }: { title: string; value: string | number }): JSX.Element {
    return (
        <div className="flex justify-between w-full">
            <div>{title}</div>
            <div>
                <strong className="pl-1.5">{value}</strong>
            </div>
        </div>
    )
}
