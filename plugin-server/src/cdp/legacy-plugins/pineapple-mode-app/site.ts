const style = `
    .button {
        position: fixed;
        bottom: 20px;
        right: 20px;
        color: black;
        font-weight: normal;
        font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
        text-align: left;
        width: 48px;
        height: 48px;
        border-radius: 100%;
        text-align: center;
        line-height: 40px;
        font-size: 32px;
        border: none;
        cursor: pointer;
        z-index: 999999;
    }
    .button:hover {
        filter: brightness(1.2);
    }
    .button.disabled {
        opacity: 0.5;
        filter: grayscale(100%);
    }
`

let rainInterval

export function inject({ config, posthog }) {
    if (config.domains) {
        const domains = config.domains.split(',').map((domain) => domain.trim())
        if (domains.length > 0 && domains.indexOf(window.location.hostname) === -1) {
            return
        }
    }

    const intensity = Math.max(1, Math.min(parseInt(config.intensity) || 5, 10))
    const emoji = config.emoji || '🍍'
    const shadow = createShadow(style)
    let buttonElement: HTMLButtonElement

    function toggle(): void {
        if (rainInterval) {
            window.clearInterval(rainInterval)
            rainInterval = undefined
            posthog.capture('Pineapple mode deactivated', config)
            buttonElement?.classList.remove('disabled')
        } else {
            rainInterval = window.setInterval(() => makeItRain(shadow, emoji, intensity), 1000 / intensity)
            posthog.capture('Pineapple mode activated', config)
            buttonElement?.classList.add('disabled')
        }
    }

    if (config.showButton === 'Yes') {
        buttonElement = Object.assign(document.createElement('button'), {
            className: 'button',
            innerText: config.buttonText || emoji,
            onclick: toggle,
        })
        Object.assign(buttonElement.style, {
            color: config.buttonColor || 'black',
            background: config.buttonBackground || '#ccae05',
        })
        shadow.appendChild(buttonElement)
    }

    if (config.startRaining === 'Yes') {
        for (let i = 0; i < intensity * 2; i++) {
            makeItRain(shadow, emoji, intensity)
        }
        toggle()
    }
}

// Drops an emoji from the sky
function makeItRain(shadow: ShadowRoot, emoji: string, intensity: number) {
    const div = document.createElement('div')
    Object.assign(div.style, {
        position: 'fixed',
        left: `${(window.innerWidth - 30) * Math.random()}px`,
        top: '-10px',
        fontSize: '24px',
        zIndex: 99999999,
        pointerEvents: 'none',
    })
    div.innerHTML = emoji
    shadow.appendChild(div)
    const duration = 300 * (10 - intensity) + Math.random() * 3001
    div.animate([{ top: '-10px' }, { top: `${window.innerHeight + 20}px` }], {
        duration,
        iterations: 1,
    })
    window.setTimeout(() => div.remove(), duration + 1)
}

function createShadow(style?: string): ShadowRoot {
    const div = document.createElement('div')
    const shadow = div.attachShadow({ mode: 'open' })
    if (style) {
        const styleElement = Object.assign(document.createElement('style'), {
            innerText: style,
        })
        shadow.appendChild(styleElement)
    }
    document.body.appendChild(div)
    return shadow
}
