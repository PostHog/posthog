interface NodeProps {
    pref: (el: HTMLDivElement | null) => void
    width?: string
    height?: string
    className?: string
    children: React.ReactNode
}

function GenericNode({ pref, height = '50px', className = '', children }: NodeProps): JSX.Element {
    return (
        <div
            ref={pref}
            className={`flex px-4 justify-center items-center space-between gap-1 bg-white border border-black border-2 rounded-lg h-[${height}] ${className}`}
        >
            {children}
        </div>
    )
}

export default GenericNode
