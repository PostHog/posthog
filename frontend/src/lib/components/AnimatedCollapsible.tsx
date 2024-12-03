import { useEffect, useRef, useState } from 'react'

export function AnimatedCollapsible({
    collapsed,
    children,
}: {
    collapsed: boolean
    children?: JSX.Element | JSX.Element[]
}): JSX.Element {
    const collapsibleSectionRef = useRef<HTMLHeadingElement>(null)

    const [height, setHeight] = useState<number | undefined>(collapsed ? 0 : undefined)

    useEffect(() => {
        if (!collapsed) {
            if (collapsibleSectionRef.current) {
                setHeight(collapsibleSectionRef.current?.getBoundingClientRect().height)
            }
        } else {
            setHeight(0)
        }
    }, [collapsed, children])

    return (
        <div
            className="collapsible overflow-hidden transition-all duration-100 ease-in-out"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                height,
            }}
        >
            <div ref={collapsibleSectionRef}>{children}</div>
        </div>
    )
}
