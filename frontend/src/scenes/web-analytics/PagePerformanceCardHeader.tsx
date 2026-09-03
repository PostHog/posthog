export function PagePerformanceCardHeader({ title }: { title: string }): JSX.Element {
    return (
        <div className="flex items-baseline gap-2 border-b px-3 py-2">
            <h3 className="m-0 text-sm font-semibold">{title}</h3>
        </div>
    )
}
