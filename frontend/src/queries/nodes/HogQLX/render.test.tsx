import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { parseHogQLX, renderHogQLX } from '~/queries/nodes/HogQLX/render'

describe('HogQLX', () => {
    describe('parse', () => {
        it('should parse tags', () => {
            const value = parseHogQLX(['__hx_tag', 'Sparkline', 'data', [1, 2, 3], 'type', ['line']])
            expect(value).toEqual({
                __hx_tag: 'Sparkline',
                data: [1, 2, 3],
                type: ['line'],
            })
        })

        it('should parse empty tags', () => {
            const value = parseHogQLX(['__hx_tag', 'Sparkline'])
            expect(value).toEqual({
                __hx_tag: 'Sparkline',
            })
        })

        it('should parse objects', () => {
            const value = parseHogQLX(['__hx_tag', '__hx_obj', 'a', 1, 'b', 2])
            expect(value).toEqual({
                a: 1,
                b: 2,
            })
        })

        it('should handle arrays', () => {
            const value = parseHogQLX(['a', 'b', 'c'])
            expect(value).toEqual(['a', 'b', 'c'])
        })

        it('should handle nested arrays', () => {
            const value = parseHogQLX(['a', ['b', 'c']])
            expect(value).toEqual(['a', ['b', 'c']])
        })

        it('should handle nested objects', () => {
            const value = parseHogQLX(['__hx_tag', '__hx_obj', 'a', ['b', 'c']])
            expect(value).toEqual({
                a: ['b', 'c'],
            })
        })

        it('should handle nested objects with tags', () => {
            const value = parseHogQLX([
                '__hx_tag',
                '__hx_obj',
                'a',
                ['__hx_tag', 'Sparkline', 'data', [1, 2, 3], 'type', ['line']],
            ])
            expect(value).toEqual({
                a: {
                    __hx_tag: 'Sparkline',
                    data: [1, 2, 3],
                    type: ['line'],
                },
            })
        })
    })

    describe('render', () => {
        it.each([
            '/uploaded_media/0190f5a2-3b4c-7d8e-9f01-23456789abcd',
            'data:image/png;base64,aGVsbG8=',
            'data:image/svg+xml,%3Csvg%20xmlns="http://www.w3.org/2000/svg"/%3E',
            'data:image/svg+xml;charset=utf-8,%3Csvg/%3E',
            'data:image/svg+xml;utf8,%3Csvg/%3E',
            'data:image/svg+xml;base64,PHN2Zy8+',
        ])('renders an image from %s', (src) => {
            const { container } = render(
                renderHogQLX(['__hx_tag', 'img', 'src', src, 'alt', 'Customer logo', 'width', 24, 'height', 16])
            )
            const image = container.querySelector('img')
            expect(image).toHaveAttribute('src', src)
            expect(image).toHaveAttribute('alt', 'Customer logo')
            expect(image).toHaveStyle({ width: '24px', height: '16px' })
        })

        it.each([
            null,
            { toString: 'bad' },
            'javascript:alert(1)',
            'https://example.com/logo.svg',
            '/uploaded/logo.png',
            '/oauth/authorize?redirect_uri=https%3A%2F%2Fexample.com',
            '/uploaded_media/0190f5a2-3b4c-7d8e-9f01-23456789abcd' + '?next=https://example.com',
            '/uploaded_media/../oauth/authorize',
            'http://example.com/logo.png',
            '//example.com/logo.png',
            '/\\example.com/logo.png',
            'data:text/html,<svg onload="alert(1)"/>',
            'data:image/svg+xml,' + 'a'.repeat(64 * 1024),
        ])('does not load an invalid image source (%#)', (src) => {
            const { container } = render(renderHogQLX({ __hx_tag: 'img', src, alt: 'Customer logo' }))
            expect(container.querySelector('img')).toBeNull()
            expect(container.textContent).toBe('Customer logo')
        })

        it.each([
            [undefined, 24],
            ['24', 24],
            [128, 24],
            [16, 16],
            [10000, 24],
            [-1, 24],
            [0, 24],
            ['100%', 24],
            [{ toString: 'bad' }, 24],
        ])('bounds image dimensions (%#)', (size, expected) => {
            const { container } = render(
                renderHogQLX({ __hx_tag: 'img', src: 'data:image/png;base64,aGVsbG8=', width: size, height: size })
            )
            expect(container.querySelector('img')).toHaveStyle({ width: `${expected}px`, height: `${expected}px` })
        })

        it('only forwards allowed image attributes', () => {
            const { container } = render(
                renderHogQLX({
                    __hx_tag: 'img',
                    src: 'data:image/png;base64,aGVsbG8=',
                    alt: { toString: 'bad' },
                    onload: 'alert(1)',
                    srcSet: 'https://example.com/other.svg 2x',
                    style: { width: 10000 },
                    children: '<svg onload="alert(1)"/>',
                })
            )
            const image = container.querySelector('img')
            expect(image).toHaveAttribute('alt', '')
            expect(image).not.toHaveAttribute('onload')
            expect(image).not.toHaveAttribute('srcset')
            expect(image).toHaveStyle({ width: '24px' })
            expect(container.querySelector('svg')).toBeNull()
        })

        it.each(['Claude', 'Unknown mark', 'constructor', 'toString', '__proto__'])(
            'renders a query label with %s mark',
            (mark) => {
                const { container } = render(
                    renderHogQLX(['__hx_tag', 'BrandMarkLabel', 'label', 'Claude Code', 'mark', mark])
                )

                expect(container.textContent).toContain('Claude Code')
                expect(container.querySelector('svg')).not.toBeNull()
            }
        )

        it.each([
            ['label', { toString: 'bad' }, 'Claude'],
            ['mark', 'Claude Code', { toString: 'bad' }],
        ])('does not throw for an object %s', (_, label, mark) => {
            const { container } = render(renderHogQLX({ __hx_tag: 'BrandMarkLabel', label, mark }))
            expect(container.textContent).toBe(typeof label === 'string' ? label : '')
            expect(container.querySelector('svg') !== null).toBe(typeof label === 'string')
        })

        it('should render Sparkline', () => {
            const value = {
                __hx_tag: 'Sparkline',
                data: [1, 2, 3],
                type: ['line'],
            }
            const element = renderHogQLX(value)
            expect(element).toMatchSnapshot()
        })

        it('should render object', () => {
            const value = {
                a: 1,
                b: 2,
            }
            const element = renderHogQLX(value)
            expect(element).toMatchSnapshot()
        })

        it('should render unknown tag', () => {
            const value = {
                __hx_tag: 'Unknown',
            }
            const element = renderHogQLX(value)
            expect(element).toMatchSnapshot()
        })

        it('should render array', () => {
            const value = [1, 2, 3]
            const element = renderHogQLX(value)
            expect(element).toMatchSnapshot()
        })
    })
})
