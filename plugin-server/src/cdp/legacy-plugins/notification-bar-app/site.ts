export function inject({ config }) {
    if (config.domains) {
        const domains = config.domains.split(',').map((domain) => domain.trim())
        if (domains.length > 0 && domains.indexOf(window.location.hostname) === -1) {
            return
        }
    }
    const localStorageKey = `notification-${config.notification}`
    if (config.rememberClose === 'yes' && localStorage.getItem(localStorageKey)) {
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
            color: ${config.textColor || 'default'};
            background: ${config.backgroundColor || 'default'};
            font-weight: normal;
            font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
            text-align: center;
            position: ${config.position === 'sticky' ? 'fixed' : 'absolute'};
            left: 0;
            top: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            z-index: 9999999;
        }
        .notification-bar a {
            color: ${config.linkColor || config.textColor || 'default'};
        }
        .notification-bar p {
            margin: 0;
        }
        ${config.cssOverride || ''}
    `
    const paragraph = Object.assign(document.createElement('p'), {
        innerHTML: config.notification,
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
        title: config.buttonTitle || '',
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
