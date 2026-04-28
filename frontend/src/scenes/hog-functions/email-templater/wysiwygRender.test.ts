import { isReactEmailSource } from './wysiwygRender'

describe('isReactEmailSource', () => {
    it('treats raw html as not react-email', () => {
        expect(isReactEmailSource('<div>Hello</div>')).toBe(false)
        expect(isReactEmailSource('<p>foo</p><span>bar</span>')).toBe(false)
        expect(isReactEmailSource('')).toBe(false)
    })

    it('detects capitalized JSX components as react-email', () => {
        expect(isReactEmailSource('<Html><Body><Text>Hi</Text></Body></Html>')).toBe(true)
        expect(isReactEmailSource('<Container>...</Container>')).toBe(true)
    })

    it('detects export default as react-email', () => {
        expect(isReactEmailSource('export default function MyEmail() { return <div/> }')).toBe(true)
    })
})
