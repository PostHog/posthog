export default function TabScroller({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="relative w-full overflow-auto">
            <div className="absolute bottom-0 left-0 right-0 top-0 flex-1">{children}</div>
        </div>
    )
}
