import React from 'react'

/*
 * If you pass icons directly to react-slick arrows, you get console errors for applying carousel-specific props.
 * Follow this thread for updates: https://github.com/akiran/react-slick/issues/1195
 * */

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function ContainedCarouselArrow({
    currentSlide,
    slideCount,
    children,
    ...props
}: {
    currentSlide?: number
    slideCount?: number
    children: React.ReactNode
    props?: Record<string, string>
}): JSX.Element {
    return <span {...props}>{children}</span>
}
