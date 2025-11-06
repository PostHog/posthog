import { useEffect, useRef, useState } from 'react'

export function AnimatedCollapsible({
    collapsed,
    autoHeight,
    children,
}: {
    collapsed: boolean
    autoHeight?: boolean
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

    // Observe height changes in the content, if autoHeight is true
    // Covers the case where the content is dynamically updated and the height needs to be updated
    useEffect(() => {
        if (!autoHeight) {
            return
        }

        if (!collapsed && collapsibleSectionRef.current) {
            const resizeObserver = new ResizeObserver((entries) => {
                for (const entry of entries) {
                    setHeight(entry.contentRect.height)
                }
            })

            resizeObserver.observe(collapsibleSectionRef.current)

            return () => {
                resizeObserver.disconnect()
            }
        }
    }, [collapsed, autoHeight])

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
