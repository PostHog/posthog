from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=True,
    type="site_app",
    id="template-notification-bar",
    name="Notification Bar",
    description="Show a notification bar for your users",
    icon_url="/static/hedgehog/list-hog.png",
    category=["Custom", "Analytics"],
    code_language="javascript",
    code="""
export function onLoad({ inputs }) {
    if (inputs.domains) {
        const domains = inputs.domains.split(',').map((domain) => domain.trim())
        if (domains.length > 0 && domains.indexOf(window.location.hostname) === -1) {
            return
        }
    }
    const localStorageKey = `notification-${inputs.notification}`
    if (inputs.rememberClose === 'yes' && localStorage.getItem(localStorageKey)) {
        return
    }
    const style = `
        .notification-bar-container {
            min-height: 56px;
        }
        .notification-bar {
            width: 100%;
            min-height: 56px;
            line-height: 36px;
            font-size: 24px;
            color: ${inputs.textColor || 'default'};
            background: ${inputs.backgroundColor || 'default'};
            font-weight: normal;
            font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
            text-align: center;
            position: ${inputs.position === 'sticky' ? 'fixed' : 'absolute'};
            left: 0;
            top: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            z-index: 9999999;
        }
        .notification-bar a {
            color: ${inputs.linkColor || inputs.textColor || 'default'};
        }
        .notification-bar p {
            margin: 0;
        }
    `
    const paragraph = Object.assign(document.createElement('p'), {
        innerHTML: inputs.notification,
    })
    const notificationElementContainer = Object.assign(document.createElement('div'), {
        className: 'notification-bar-container',
    })
    const notificationElement = Object.assign(document.createElement('div'), {
        className: 'notification-bar',
        onclick: (e) => {
            if (!e.target.matches('a,button')) {
                notificationElement.style.display = 'none'
                notificationElementContainer.style.display = 'none'
                window.localStorage.setItem(localStorageKey, 'true')
            }
        },
        title: inputs.buttonTitle || '',
    })
    notificationElement.append(paragraph)
    const shadow = createShadowRoot(style)
    notificationElementContainer.appendChild(notificationElement)
    shadow.appendChild(notificationElementContainer)
    document.body.prepend(shadow)
}
function createShadowRoot(style) {
    const div = document.createElement('div')
    const shadow = div.attachShadow({ mode: 'open' })
    if (style) {
        const styleElement = Object.assign(document.createElement('style'), {
            innerText: style,
        })
        shadow.appendChild(styleElement)
    }
    document.body.prepend(div)
    return shadow
}
""".strip(),
    inputs_schema=[
        {
            "key": "domains",
            "label": "Domains",
            "description": 'Comma separated list of domains to activate on. Leave blank to enable all. For example: "localhost,app.posthog.com"',
            "type": "string",
            "default": "",
        },
        {
            "key": "notification",
            "label": "HTML to show in the notification bar",
            "type": "string",
            "default": "🚀 <strong>Product 2.0!</strong> is out! <a href='https://google.com'>Click here</a> to learn more.",
            "required": True,
        },
        {
            "key": "position",
            "label": "Position of the notification bar",
            "type": "choice",
            "choices": [
                {
                    "label": "Sticky",
                    "value": "sticky",
                },
                {
                    "label": "Top of page",
                    "value": "top-of-page",
                },
            ],
            "default": "sticky",
            "required": True,
        },
        {
            "key": "backgroundColor",
            "label": "Background color",
            "type": "string",
            "default": "#ebece8",
            "required": True,
        },
        {
            "key": "textColor",
            "label": "Text color",
            "type": "string",
            "default": "#333",
            "required": True,
        },
        {
            "key": "linkColor",
            "label": "Link color",
            "type": "string",
            "default": "#f64e00",
            "required": True,
        },
        {
            "key": "rememberClose",
            "label": "Remember close",
            "type": "choice",
            "choices": [
                {
                    "label": "Yes",
                    "value": "yes",
                },
                {
                    "label": "No",
                    "value": "no",
                },
            ],
            "default": "yes",
            "description": "Remember if the user has closed the notification bar, and don't show it again. This resets if you update the notification bar's text.",
        },
    ],
)
