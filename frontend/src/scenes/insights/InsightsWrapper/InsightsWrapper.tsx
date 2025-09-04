// These classes are all pretty weird but they're here because we want to maintain consistency
// between the trends insights and some other nodes
export const InsightsWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => {
    return (
        <div className="InsightVizDisplay InsightVizDisplay--type-trends border rounded bg-surface-primary">
            <div className="InsightVizDisplay__content">{children}</div>
        </div>
    )
}
