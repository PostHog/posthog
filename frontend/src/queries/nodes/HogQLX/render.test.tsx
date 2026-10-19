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
        it.each(['Claude', 'Unknown mark'])('renders a query label with %s mark', (mark) => {
            const { container } = render(
                renderHogQLX(['__hx_tag', 'BrandMarkLabel', 'label', 'Claude Code', 'mark', mark])
            )

            expect(container.textContent).toContain('Claude Code')
            expect(container.querySelector('svg')).not.toBeNull()
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
