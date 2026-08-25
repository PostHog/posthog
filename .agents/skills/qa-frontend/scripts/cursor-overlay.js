// Visible cursor overlay for recorded QA demo passes. Injected via the browser
// tool's evaluate/eval into the page being recorded; the overlay is visual only
// (pointer-events: none) and never affects the page under test. Re-inject after
// every navigation. Exposes window.__qaCursor.glide(x, y, ms) for smooth
// movement before a click; real mousemove/mousedown events also drive it, so
// plain element clicks still show the cursor jumping to the target and rippling.
;(() => {
    if (window.__qaCursor) {
        return 'already injected'
    }
    // keep in sync with the colors in scripts/annotate-evidence.py
    const BRAND_RED = '#f54e00'
    const cursor = document.createElement('div')
    cursor.setAttribute('data-qa-cursor', '')
    cursor.style.cssText = [
        'position: fixed',
        'z-index: 2147483647',
        'width: 22px',
        'height: 22px',
        'margin: -4px 0 0 -3px',
        'pointer-events: none',
        'transition: none',
        'left: -100px',
        'top: -100px',
    ].join(';')
    cursor.innerHTML =
        '<svg width="22" height="22" viewBox="0 0 22 22">' +
        '<path d="M4 2 L4 17 L8 13.5 L11 20 L13.5 19 L10.5 12.5 L16 12 Z" ' +
        'fill="#fff" stroke="#151515" stroke-width="1.4" stroke-linejoin="round"/></svg>'
    document.documentElement.appendChild(cursor)

    const moveTo = (x, y) => {
        cursor.style.left = x + 'px'
        cursor.style.top = y + 'px'
    }

    const ripple = (x, y) => {
        const ring = document.createElement('div')
        ring.style.cssText = [
            'position: fixed',
            'z-index: 2147483646',
            'left: ' + (x - 18) + 'px',
            'top: ' + (y - 18) + 'px',
            'width: 36px',
            'height: 36px',
            'border: 3px solid ' + BRAND_RED,
            'border-radius: 50%',
            'pointer-events: none',
            'opacity: 0.9',
            'transform: scale(0.35)',
            'transition: transform 450ms ease-out, opacity 450ms ease-out',
        ].join(';')
        document.documentElement.appendChild(ring)
        requestAnimationFrame(() => {
            ring.style.transform = 'scale(1)'
            ring.style.opacity = '0'
        })
        setTimeout(() => ring.remove(), 500)
    }

    document.addEventListener('mousemove', (e) => moveTo(e.clientX, e.clientY), true)
    document.addEventListener('mousedown', (e) => ripple(e.clientX, e.clientY), true)

    const CHIP_COLORS = { pass: '#388600', fail: '#db3707', info: '#1d4aff' }
    let captionBar = null

    const caption = (text, status = 'info') => {
        if (!text) {
            if (captionBar) {
                captionBar.remove()
                captionBar = null
            }
            return 'caption cleared'
        }
        if (!captionBar) {
            captionBar = document.createElement('div')
            captionBar.setAttribute('data-qa-caption', '')
            captionBar.style.cssText = [
                'position: fixed',
                'left: 0',
                'right: 0',
                'bottom: 0',
                'z-index: 2147483645',
                'display: flex',
                'align-items: center',
                'gap: 14px',
                'padding: 12px 18px',
                'background: #151515',
                'color: #eeefe9',
                'font: 600 17px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
                'pointer-events: none',
            ].join(';')
            captionBar.innerHTML = '<span data-qa-chip></span><span data-qa-text></span>'
            document.documentElement.appendChild(captionBar)
        }
        const chip = captionBar.querySelector('[data-qa-chip]')
        chip.textContent = status.toUpperCase()
        chip.style.cssText = [
            'background: ' + (CHIP_COLORS[status] || CHIP_COLORS.info),
            'color: #fff',
            'padding: 3px 14px',
            'border-radius: 999px',
            'font-size: 15px',
            'flex: none',
        ].join(';')
        captionBar.querySelector('[data-qa-text]').textContent = text
        return 'caption set'
    }

    window.__qaCursor = {
        caption,
        glide(x, y, ms = 500) {
            const startX = parseFloat(cursor.style.left) || 0
            const startY = parseFloat(cursor.style.top) || 0
            const start = performance.now()
            const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
            return new Promise((resolve) => {
                const step = (now) => {
                    const t = Math.min(1, (now - start) / ms)
                    const k = ease(t)
                    moveTo(startX + (x - startX) * k, startY + (y - startY) * k)
                    if (t < 1) {
                        requestAnimationFrame(step)
                    } else {
                        resolve('done')
                    }
                }
                requestAnimationFrame(step)
            })
        },
        moveTo,
        ripple,
    }
    return 'injected'
})()
