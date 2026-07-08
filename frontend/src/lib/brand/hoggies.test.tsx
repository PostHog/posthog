import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { pngHoggie } from './hoggies'

describe('pngHoggie', () => {
    afterEach(() => {
        cleanup()
    })

    // The shipped regression: call sites build the component in a top-level `const`
    // (`const Hog = pngHoggie(mod)`), so a module that resolves to null/undefined must not
    // throw when `pngHoggie` is called - that would take down the whole importing module.
    test.each([[null], [undefined]])('does not throw and renders nothing for a %s module', (mod) => {
        const Hog = pngHoggie(mod)
        const { container } = render(<Hog />)
        expect(container.querySelector('img')).toBeNull()
    })

    it('renders an <img> from the module src and aspect ratio', () => {
        const Hog = pngHoggie({ src: 'construction-2.png', aspectRatio: 2 })
        const { container } = render(<Hog />)
        const img = container.querySelector('img')
        expect(img).not.toBeNull()
        expect(img).toHaveAttribute('src', 'construction-2.png')
        expect(img?.style.aspectRatio).toBe('2')
    })
})
