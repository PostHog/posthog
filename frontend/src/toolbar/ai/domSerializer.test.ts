import { TOOLBAR_ID } from '~/toolbar/utils'

import { serializeDOM } from './domSerializer'

describe('serializeDOM', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        document.title = 'Test page'
    })

    it('captures basic DOM structure', () => {
        document.body.innerHTML = `
            <header class="nav-header">
                <nav role="navigation">
                    <a class="logo" href="/">PostHog</a>
                    <button class="cta-button" data-ph-capture="true">Get started</button>
                </nav>
            </header>
        `

        const snapshot = serializeDOM()
        expect(snapshot.tree).toContain('<header .nav-header>')
        expect(snapshot.tree).toContain('<nav role="navigation">')
        expect(snapshot.tree).toContain('<a .logo href="/">')
        expect(snapshot.tree).toContain('PostHog')
        expect(snapshot.tree).toContain('data-ph-capture="true"')
        expect(snapshot.tree).toContain('Get started')
    })

    it('skips the toolbar element entirely', () => {
        document.body.innerHTML = `
            <main>Visible content</main>
            <div id="${TOOLBAR_ID}"><span class="should-not-appear">internal</span></div>
        `

        const snapshot = serializeDOM()
        expect(snapshot.tree).toContain('Visible content')
        expect(snapshot.tree).not.toContain('should-not-appear')
        expect(snapshot.tree).not.toContain(TOOLBAR_ID)
    })

    it('skips script, style, and noscript content', () => {
        document.body.innerHTML = `
            <main>
                <script>const secret = 'do not include'</script>
                <style>.foo { color: red }</style>
                <noscript>fallback</noscript>
                <p>Visible paragraph</p>
            </main>
        `

        const snapshot = serializeDOM()
        expect(snapshot.tree).toContain('Visible paragraph')
        expect(snapshot.tree).not.toContain('do not include')
        expect(snapshot.tree).not.toContain('color: red')
        expect(snapshot.tree).not.toContain('fallback')
    })

    it('renders svg as a leaf without descending into its internals', () => {
        document.body.innerHTML = `
            <div>
                <svg viewBox="0 0 10 10"><path d="M0 0L10 10"/></svg>
            </div>
        `

        const snapshot = serializeDOM()
        expect(snapshot.tree).toContain('<svg />')
        expect(snapshot.tree).not.toContain('<path')
    })

    it('skips elements with display: none, visibility: hidden, or aria-hidden', () => {
        document.body.innerHTML = `
            <div style="display: none">hidden by display</div>
            <div style="visibility: hidden">hidden by visibility</div>
            <div aria-hidden="true">hidden by aria</div>
            <p>visible</p>
        `

        const snapshot = serializeDOM()
        expect(snapshot.tree).not.toContain('hidden by display')
        expect(snapshot.tree).not.toContain('hidden by visibility')
        expect(snapshot.tree).not.toContain('hidden by aria')
        expect(snapshot.tree).toContain('visible')
    })

    it('truncates long text content', () => {
        const longText = 'a'.repeat(300)
        document.body.innerHTML = `<p>${longText}</p>`

        const snapshot = serializeDOM({ maxTextLength: 50 })
        expect(snapshot.tree).toContain('a'.repeat(50) + '...')
        expect(snapshot.tree).not.toContain('a'.repeat(60))
    })

    it('respects maxNodes and emits a truncation comment', () => {
        const items: string[] = []
        for (let i = 0; i < 50; i++) {
            items.push(`<li>item ${i}</li>`)
        }
        document.body.innerHTML = `<ul>${items.join('')}</ul>`

        const snapshot = serializeDOM({ maxNodes: 5 })
        expect(snapshot.tree).toContain('<!-- truncated -->')
        // Expect we stopped well before all 50 items were rendered
        expect(snapshot.tree.split('item').length - 1).toBeLessThan(10)
    })

    it('respects maxDepth', () => {
        document.body.innerHTML = `
            <div><div><div><div><div><span>deep</span></div></div></div></div></div>
        `
        const snapshot = serializeDOM({ maxDepth: 2 })
        expect(snapshot.tree).toContain('<!-- truncated -->')
        expect(snapshot.tree).not.toContain('deep')
    })

    it('emits id, classes, role, aria-label, and data-ph attributes', () => {
        document.body.innerHTML = `
            <button id="signup" class="btn primary extra ignored"
                role="button" aria-label="Sign up now"
                data-ph-capture="signup_click" data-ph-event="signup">
                Sign up
            </button>
        `
        const snapshot = serializeDOM()
        expect(snapshot.tree).toContain('#signup')
        expect(snapshot.tree).toContain('.btn')
        expect(snapshot.tree).toContain('.primary')
        expect(snapshot.tree).toContain('.extra')
        // First 3 classes only
        expect(snapshot.tree).not.toContain('.ignored')
        expect(snapshot.tree).toContain('role="button"')
        expect(snapshot.tree).toContain('aria-label="Sign up now"')
        expect(snapshot.tree).toContain('data-ph-capture="signup_click"')
        expect(snapshot.tree).toContain('data-ph-event="signup"')
    })

    it('returns viewport, url, and title metadata', () => {
        document.title = 'Some title'
        document.body.innerHTML = '<p>x</p>'
        const snapshot = serializeDOM()
        expect(snapshot.title).toBe('Some title')
        expect(typeof snapshot.url).toBe('string')
        expect(snapshot.viewport.width).toBeGreaterThanOrEqual(0)
        expect(snapshot.viewport.height).toBeGreaterThanOrEqual(0)
    })

    it('handles empty body gracefully', () => {
        document.body.innerHTML = ''
        const snapshot = serializeDOM()
        expect(snapshot.tree).toContain('<body>')
        expect(snapshot.tree).toContain('</body>')
    })

    it('filters out auto-generated CSS-in-JS class names', () => {
        document.body.innerHTML = `
            <div class="real-class css-1abc23 sc-foo emotion-bar"></div>
        `
        const snapshot = serializeDOM()
        expect(snapshot.tree).toContain('.real-class')
        expect(snapshot.tree).not.toContain('.css-1abc23')
        expect(snapshot.tree).not.toContain('.sc-foo')
        expect(snapshot.tree).not.toContain('.emotion-bar')
    })

    it('emits placeholder for input elements', () => {
        document.body.innerHTML = `<input type="email" name="email" placeholder="you@example.com" />`
        const snapshot = serializeDOM()
        expect(snapshot.tree).toContain('type="email"')
        expect(snapshot.tree).toContain('name="email"')
        expect(snapshot.tree).toContain('placeholder="you@example.com"')
    })
})
