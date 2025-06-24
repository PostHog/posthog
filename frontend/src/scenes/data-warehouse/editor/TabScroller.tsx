export default function TabScroller({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="relative w-full overflow-auto">
            <div className="flex-1 absolute top-0 left-0 right-0 bottom-0">{children}</div>
        </div>
    )
}
