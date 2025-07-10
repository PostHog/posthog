interface NodeProps {
    pref: (el: HTMLDivElement | null) => void
    width?: string
    height?: string
    className?: string
    children: React.ReactNode
}

function GenericNode({ pref, className = '', children }: NodeProps): JSX.Element {
    return (
        <div
            ref={pref}
            className={`space-between bg-primary flex w-[200px] items-center justify-center gap-1 rounded-lg border border-2 border-black px-4 py-3 ${className}`}
        >
            {children}
        </div>
    )
}

export default GenericNode
