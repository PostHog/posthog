// These classes are all pretty weird but they're here because we want to maintain consistency
// between the trends and top customers views
export const InsightsWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => {
    return (
        <div className="InsightVizDisplay InsightVizDisplay--type-trends bg-surface-primary rounded border">
            <div className="InsightVizDisplay__content">{children}</div>
        </div>
    )
}
