import './sidebar.scss'

export function SidebarRowEnter({
    children,
    onEntered,
}: {
    children: JSX.Element
    onEntered: () => void
}): JSX.Element {
    return (
        <div
            className="SidebarRowEnter"
            onAnimationEnd={(event) => {
                // The row's own slide bubbles up here as well. The room it opens ends the motion.
                if (event.target === event.currentTarget) {
                    onEntered()
                }
            }}
        >
            <div className="SidebarRowEnter__row">{children}</div>
        </div>
    )
}
