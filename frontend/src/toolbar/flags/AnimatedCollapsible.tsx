import './featureFlags.scss'

import React, { useEffect, useRef, useState } from 'react'

export function AnimatedCollapsible({
    collapsed,
    children,
}: {
    collapsed: boolean
    children?: JSX.Element | JSX.Element[]
}): JSX.Element {
    const collapsibleSectionRef = useRef<HTMLHeadingElement>(null)

    const [height, setHeight] = useState(0)

    useEffect(() => {
        console.log(collapsed)
        if (!collapsed) {
            if (collapsibleSectionRef.current) {
                setHeight(collapsibleSectionRef.current?.getBoundingClientRect().height)
            }
        } else {
            setHeight(0)
        }
    }, [collapsed])

    return (
        <div className="collapsible" style={{ height }}>
            <div ref={collapsibleSectionRef}>{children}</div>
        </div>
    )
}
