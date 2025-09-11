import * as d3 from 'd3'

import { D3Selector, D3Transition } from 'lib/hooks/useD3'
import { INITIAL_CONFIG } from 'scenes/insights/views/Histogram/histogramUtils'

export const getOrCreateEl = (
    container: D3Selector,
    selector: string,
    createCallback: () => D3Selector
): D3Selector => {
    const el = container.select(selector)
    if (el.empty()) {
        return createCallback()
    }
    return el
}

export const animate = (
    it: D3Selector,
    transitionDuration: number,
    isAnimated: boolean,
    toAnimate: (_it: D3Transition | D3Selector) => D3Transition | D3Selector = (_it) => _it // everything you want to animate goes here
): D3Transition | D3Selector => {
    if (isAnimated) {
        return it.transition().duration(transitionDuration).call(toAnimate)
    }
    return it.call(toAnimate)
}

export const wrap = (
    text: D3Selector,
    width: number,
    lineHeight: number = INITIAL_CONFIG.spacing.labelLineHeight,
    isVertical: boolean = true,
    dx: number = INITIAL_CONFIG.spacing.xLabel
): D3Selector => {
    const maxWidth = width - 6 // same as padding-{left|right}: 3px;
    text.each(function () {
        const _text = d3.select(this)
        const words: string[] = _text.text().split(/\s+/)
        const y = _text.attr('y'),
            dy = parseFloat(_text.attr('dy'))

        let line: string[] = [],
            lineNumber = 0,
            tspan = _text
                .text(null)
                .append('tspan')
                .attr('x', 0)
                .attr('y', y)
                .attr('dx', isVertical ? 0 : -dx + 'px')
                .attr('dy', dy + 'em')

        words.forEach((word) => {
            // try appending text. revert and break onto new line if it's just too long
            line.push(word)
            tspan.text(line.join(' '))
            if ((tspan.node()?.getComputedTextLength() || 0) > maxWidth) {
                line.pop()
                tspan.text(line.join(' '))
                line = [word]
                tspan = _text
                    .append('tspan')
                    .attr('x', 0)
                    .attr('y', y)
                    .attr('dx', isVertical ? 0 : -dx + 'px')
                    .attr('dy', ++lineNumber * lineHeight + dy + 'em')
                    .text(word)
            }
        })
    })
    return text
}
