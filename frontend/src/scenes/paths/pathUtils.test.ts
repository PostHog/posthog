import { RGBColor } from 'd3'

import { PathNodeData, pageUrl } from './pathUtils'

describe('pageUrl', () => {
    it('should correctly process PathNodeData with hash based URL', () => {
        const testData = {
            name: '2_https://example.com/#/auth/login',
            targetLinks: [
                {
                    average_conversion_time: 0,
                    index: 0,
                    value: 0,
                    width: 0,
                    y0: 0,
                    color: { r: 0, g: 0, b: 0 } as RGBColor,
                    target: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                    source: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                },
            ],
            sourceLinks: [],
            depth: 0,
            width: 0,
            height: 0,
            index: 0,
            value: 0,
            x0: 0,
            x1: 0,
            y0: 0,
            y1: 0,
            layer: 0,
            visible: true,
        } as unknown as PathNodeData

        const result = pageUrl(testData, true)
        expect(result).toBe('/#/auth/login')
    })

    it('should correctly process PathNodeData with unrelated hash in URL', () => {
        const testData = {
            name: '2_https://example.com/auth/login#sidepanel=explore',
            targetLinks: [
                {
                    average_conversion_time: 0,
                    index: 0,
                    value: 0,
                    width: 0,
                    y0: 0,
                    color: { r: 0, g: 0, b: 0 } as RGBColor,
                    target: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                    source: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                },
            ],
            sourceLinks: [],
            depth: 0,
            width: 0,
            height: 0,
            index: 0,
            value: 0,
            x0: 0,
            x1: 0,
            y0: 0,
            y1: 0,
            layer: 0,
            visible: true,
        } as unknown as PathNodeData

        const result = pageUrl(testData, true)
        expect(result).toBe('/auth/login')
    })

    it('should correctly process PathNodeData with regular URL', () => {
        const testData = {
            name: '2_https://example.com/path',
            targetLinks: [
                {
                    average_conversion_time: 0,
                    index: 0,
                    value: 0,
                    width: 0,
                    y0: 0,
                    color: { r: 0, g: 0, b: 0 } as RGBColor,
                    target: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                    source: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                },
            ],
            sourceLinks: [],
            depth: 0,
            width: 0,
            height: 0,
            index: 0,
            value: 0,
            x0: 0,
            x1: 0,
            y0: 0,
            y1: 0,
            layer: 0,
            visible: true,
        } as unknown as PathNodeData

        const result = pageUrl(testData, true)
        expect(result).toBe('/path')
    })

    it('should decode URL-encoded characters in path cleaning aliases', () => {
        const testData = {
            name: '2_https://example.com/files/<id>',
            targetLinks: [
                {
                    average_conversion_time: 0,
                    index: 0,
                    value: 0,
                    width: 0,
                    y0: 0,
                    color: { r: 0, g: 0, b: 0 } as RGBColor,
                    target: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                    source: {
                        name: '1_https://example.com/',
                        targetLinks: [],
                        sourceLinks: [],
                        depth: 0,
                        width: 0,
                        height: 0,
                        index: 0,
                        value: 0,
                        x0: 0,
                        x1: 0,
                        y0: 0,
                        y1: 0,
                        layer: 0,
                        visible: true,
                    },
                },
            ],
            sourceLinks: [],
            depth: 0,
            width: 0,
            height: 0,
            index: 0,
            value: 0,
            x0: 0,
            x1: 0,
            y0: 0,
            y1: 0,
            layer: 0,
            visible: true,
        } as unknown as PathNodeData

        // The URL API encodes < and > to %3C and %3E, but we should decode them back
        const result = pageUrl(testData, true)
        expect(result).toBe('/files/<id>')
    })
})
