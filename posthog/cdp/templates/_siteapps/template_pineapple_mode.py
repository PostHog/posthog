from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=True,
    type="site_app",
    id="template-pineapple-mode",
    name="Pineapple Mode",
    description="Make any website better by adding raining pineapples",
    icon_url="/static/services/pineapple.png",
    category=["Custom", "Analytics"],
    code_language="javascript",
    code="""
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
export function onLoad({ inputs, posthog }) {
    if (inputs.domains) {
        const domains = inputs.domains.split(',').map((domain) => domain.trim())
        if (domains.length > 0 && domains.indexOf(window.location.hostname) === -1) {
            return
        }
    }
    const intensity = Math.max(1, Math.min(parseInt(inputs.intensity) || 5, 10))
    const emoji = inputs.emoji || '🍍'
    const shadow = createShadow(style)
    let buttonElement: HTMLButtonElement
    let rainInterval
    function toggle(): void {
        if (rainInterval) {
            window.clearInterval(rainInterval)
            rainInterval = undefined
            posthog.capture('Pineapple mode deactivated', inputs)
            buttonElement?.classList.remove('disabled')
        } else {
            rainInterval = window.setInterval(() => makeItRain(shadow, emoji, intensity), 1000 / intensity)
            posthog.capture('Pineapple mode activated', inputs)
            buttonElement?.classList.add('disabled')
        }
    }
    if (inputs.showButton) {
        buttonElement = Object.assign(document.createElement('button'), {
            className: 'button',
            innerText: inputs.buttonText || emoji,
            onclick: toggle,
        })
        Object.assign(buttonElement.style, {
            color: inputs.buttonColor || 'black',
            background: inputs.buttonBackground || '#ccae05',
        })
        shadow.appendChild(buttonElement)
    }
    if (inputs.startRaining) {
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
""".strip(),
    inputs_schema=[
        {
            "key": "domains",
            "type": "string",
            "label": "Domains",
            "description": 'Comma separated list of domains to activate on. Leave blank to enable all. For example: "localhost,app.posthog.com"',
            "default": "",
        },
        {
            "key": "emoji",
            "type": "string",
            "label": "Emoji to use",
            "default": "🍍",
            "required": True,
        },
        {
            "key": "intensity",
            "type": "string",
            "label": "Intensity",
            "default": "4",
            "required": True,
            "description": "Rainfall intensity (1-10)",
        },
        {
            "key": "startRaining",
            "type": "boolean",
            "label": "Start raining immediately",
            "default": True,
            "required": True,
        },
        {
            "key": "showButton",
            "type": "boolean",
            "label": "Show Floating Button",
            "description": "Shows a button you can use to disable the pineapple mode",
            "default": True,
        },
        {"key": "buttonText", "type": "string", "label": "Button text, if enabled", "default": ""},
        {
            "key": "buttonColor",
            "type": "string",
            "label": "Button text color",
            "description": 'Any valid CSS color. For example: "#ff0000" or "red"',
            "default": "black",
        },
        {
            "key": "buttonBackground",
            "type": "string",
            "label": "Button background",
            "description": 'Any valid CSS background. For example: "red" or "url(\'...\')"',
            "default": "#ccae05",
        },
    ],
)
