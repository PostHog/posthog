import React from 'react'

import { ArrowLeftOutlined, ArrowRightOutlined } from '@ant-design/icons'

/*
 * Why use this Component?
 * If you pass icons directly to react-slick arrows, you get console errors for applying carousel-specific props.
 * Follow this thread for updates: https://github.com/akiran/react-slick/issues/1195
 * */

export function CarouselArrow({
    direction,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    currentSlide,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    slideCount,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    ...props
}: {
    direction: 'next' | 'prev'
    currentSlide?: number
    slideCount?: number
    props?: Record<string, string>
}): JSX.Element {
    return <span {...props}>{direction === 'prev' ? <ArrowLeftOutlined /> : <ArrowRightOutlined />}</span>
}
