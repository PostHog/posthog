import { act, cleanup, render, screen } from '@testing-library/react'

import { ThemeProvider, useTheme } from './theme-provider'

function ThemeReadout(): JSX.Element {
    const { theme, setTheme } = useTheme()
    return (
        <button type="button" onClick={() => setTheme('dark')}>
            {theme}
        </button>
    )
}

describe('ThemeProvider', () => {
    const originalLocalStorage = Object.getOwnPropertyDescriptor(window, 'localStorage')
    const originalMatchMedia = window.matchMedia

    beforeEach(() => {
        window.matchMedia = ((query: string) => ({
            matches: false,
            media: query,
            addEventListener: () => {},
            removeEventListener: () => {},
        })) as unknown as typeof window.matchMedia
    })

    afterEach(() => {
        cleanup()
        window.matchMedia = originalMatchMedia
        if (originalLocalStorage) {
            Object.defineProperty(window, 'localStorage', originalLocalStorage)
        }
        document.documentElement.classList.remove('light', 'dark')
    })

    it('renders and changes theme when the browser refuses localStorage', () => {
        Object.defineProperty(window, 'localStorage', {
            configurable: true,
            get: () => {
                throw new DOMException('Access is denied for this document.', 'SecurityError')
            },
        })

        render(
            <ThemeProvider defaultTheme="light" disableTransitionOnChange={false}>
                <ThemeReadout />
            </ThemeProvider>
        )
        expect(screen.getByText('light')).toBeTruthy()

        act(() => screen.getByText('light').click())

        expect(screen.getByText('dark')).toBeTruthy()
        expect(document.documentElement.classList.contains('dark')).toBe(true)
    })
})
