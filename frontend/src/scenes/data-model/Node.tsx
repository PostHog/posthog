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
            className={`flex w-[200px] px-4 py-3 justify-center items-center space-between gap-1 bg-primary border border-black border-2 rounded-lg ${className}`}
        >
            {children}
        </div>
    )
}

export default GenericNode
