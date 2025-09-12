from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=True,
    type="site_app",
    id="template-early-access-features",
    name="Early Access Features App",
    description="This app is used with Early Access Feature Management",
    icon_url="https://raw.githubusercontent.com/PostHog/early-access-features-app/refs/heads/main/logo.png",
    category=["Custom"],
    code_language="javascript",
    code="""
const style = (inputs) => `
    .list-container {
        flex: 1;
        flex-direction: row;
        overflow-y: auto;
    }

    .info {
        flex: 2;
    }

    .list-item {
        padding: 15px 30px;
        height: 35%;
        display: flex;
        flex-direction: row;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #00000026;

        .list-item-name {
            font-size: 18px;
        }

        .list-item-description {
            font-size: 14px;
        }

        .list-item-documentation-link {
            margin-top: 15px;

            .label {
                text-decoration: none;
            }
        }
    }

    .list-content {
        margin-right: 20px;
    }

    .beta-feature-button {
        position: fixed;
        bottom: 20px;
        right: 20px;
        font-weight: normal;
        font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
        text-align: left;
        z-index: ${parseInt(inputs.zIndex) || 99999};
        display: flex;
        justify-content: center;
        align-items: center;
    }

    .top-section {
        padding: 15px 30px;
        display: flex;
        flex-direction: row;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #00000026;
    }

    .beta-list-cancel {
        cursor: pointer;
    }

    .title {
        font-size: 16px;
        font-weight: bold;
    }

    .popup {
        position: fixed;
        top: 50%;
        left: 50%;
        color: black;
        transform: translate(-50%, -50%);
        font-weight: normal;
        font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
        text-align: left;
        z-index: ${parseInt(inputs.zIndex) || 99999};

        display: none;
        flex-direction: column;
        background: white;
        border: 1px solid #f0f0f0;
        border-radius: 8px;
        padding-top: 5px;
        width: 40rem;
        height: 50%;
        box-shadow: -6px 0 16px -8px rgb(0 0 0 / 8%), -9px 0 28px 0 rgb(0 0 0 / 5%), -12px 0 48px 16px rgb(0 0 0 / 3%);
    }

    .beta-feature-button {
        width: 64px;
        height: 64px;
        border-radius: 100%;
        text-align: center;
        line-height: 60px;
        font-size: 32px;
        border: none;
        cursor: pointer;
    }
    .beta-feature-button:hover {
        filter: brightness(1.2);
    }

    .empty-prompt {
        flex: 1;
        text-align: center;
        margin-top: 20px;
    }

    /* The switch - the box around the slider */
    .switch {
        margin-left: 10px;
        margin-right: 10px;
        position: relative;
        display: inline-block;
        min-width: 50px;
        height: 24px;
    }

    /* Hide default HTML checkbox */
    .switch input {
        opacity: 0;
        width: 0;
        height: 0;
    }

    /* The slider */
    .slider {
        position: absolute;
        cursor: pointer;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background-color: #00000026;
        -webkit-transition: .4s;
        transition: background-color .4s;
        cursor: pointer;
    }

    .slider:before {
        position: absolute;
        content: "";
        height: 20px;
        width: 20px;
        left: -10px;
        bottom: -6px;
        background-color: #ffffff;
        -webkit-transition: .2s;
        transition: .2s;
        border: 2px solid #00000026;
    }

    input:checked + .slider {
        background-color: #00000026;
    }

    input:focus + .slider {
        box-shadow: 0 0 1px #00000026;
    }

    input:checked + .slider:before {
        -webkit-transform: translateX(26px);
        -ms-transform: translateX(26px);
        transform: translateX(26px);
        background-color: #1d4aff;
    }

    /* Rounded sliders */
    .slider.round {
        border-radius: 20px;
        height: 10px;
        width: 30px;
        background-color: #00000026;
    }

    .slider.round:before {
        border-radius: 50%;
    }

    .loader-container {
        display: flex;
        justify-content: center;
        align-items: center;
        height: 50%;
        width: 100%;
    }

    .loader {
        border: 8px solid #00000026; /* Light grey */
        border-top: 8px solid #1d4aff; /* Blue */
        border-radius: 50%;
        width: 60px;
        height: 60px;
        animation: spin 2s linear infinite;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`

interface PreviewItem {
    name: string
    description: string
    flagKey: string
    documentationUrl: string
}

export function onLoad({ inputs, posthog }) {
    if (inputs.domains) {
        const domains = inputs.domains.split(',').map((domain) => domain.trim())
        if (domains.length > 0 && domains.indexOf(window.location.hostname) === -1) {
            return
        }
    }
    const shadow = createShadow(style(inputs))

    function optIn(flagKey: string) {
        posthog.updateEarlyAccessFeatureEnrollment(flagKey, true)
    }

    function optOut(flagKey: string) {
        posthog.updateEarlyAccessFeatureEnrollment(flagKey, false)
    }

    function openbugBox() {
        posthog.getEarlyAccessFeatures((previewItemData) => {
            const betaListContainer = shadow.getElementById('list-container')
            if (betaListContainer) {
                const previewItems = listItemComponents(previewItemData)
                const previewList = previewItems
                    ? `
                    <div class="list">
                        ${previewItems}
                    </div>
                `
                    : `
                    <div class="empty-prompt">
                        No beta features available
                    </div>
                `
                betaListContainer.innerHTML = previewList

                previewItemData.forEach((item, index) => {
                    const checkbox = shadow.querySelector('.checkbox-' + index)
                    checkbox?.addEventListener('click', (e) => {
                        if (e.target?.checked) {
                            optIn(item.flagKey)
                        } else {
                            optOut(item.flagKey)
                        }
                    })
                })
            }
        }, true) // Force reload always

        Object.assign(listElement.style, { display: 'flex' })

        const closeButton = shadow.querySelector('.beta-list-cancel')
        closeButton?.addEventListener('click', (e) => {
            e.preventDefault()
            Object.assign(listElement.style, { display: 'none' })
        })

        // // Hide when clicked outside
        // const _betaList = document.getElementById('beta-list')
        // document.addEventListener('click', function(event) {
        //     const isClickInside = _betaList?.contains(event.target)

        //     if (!isClickInside) {
        //         // Object.assign(formElement.style, { display: 'none' })
        //     }
        // });
    }

    // TODO: Make this button a inputs option
    const buttonElement = Object.assign(document.createElement('button'), {
        className: 'beta-feature-button',
        onclick: openbugBox,
        title: inputs.buttonTitle || '',
    })

    buttonElement.innerHTML = `
        <svg viewBox="0 0 100 80" width="30" height="30">
            <rect width="100" height="10" fill="white"></rect>
            <rect y="30" width="100" height="10" fill="white"></rect>
            <rect y="60" width="100" height="10" fill="white"></rect>
        </svg>
    `

    Object.assign(buttonElement.style, {
        color: inputs.buttonColor || 'white',
        background: inputs.buttonBackground || '#1d4aff',
    })

    if (inputs.useButton === 'Yes') {
        shadow.appendChild(buttonElement)
    }

    const CloseButtonComponent = (width: number, height: number) => `
        <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" fill="currentColor" class="bi bi-x" viewBox="0 0 16 16">
            <path d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708z"/>
        </svg>
    `

    const BetaListComponent = `
        <div class='top-section'>
            <div class='title'>Enable beta features</div>
            <div class='beta-list-cancel'>
                ${CloseButtonComponent(30, 30)}
            </div>
        </div>
        <div id="list-container" class="list-container">
            <div class="loader-container">
                <div class="loader"></div>
            </div>
        </div>
    `

    const betaListElement = document.createElement('div')
    betaListElement.id = 'beta-list'
    const listElement = Object.assign(betaListElement, {
        className: 'popup',
        innerHTML: BetaListComponent,
    })

    shadow.appendChild(listElement)

    if (inputs.selector) {
        const clickListener = (e) => {
            if (e.target.closest(inputs.selector)) {
                openbugBox()
            }
        }
        window.addEventListener('click', clickListener)
    }

    const listItemComponents = (items?: PreviewItem[]) => {
        if (items) {
            return items
                .map((item, index) => {
                    const checked = posthog.isFeatureEnabled(item.flagKey)

                    const documentationLink = item.documentationUrl
                        ? `<div class='list-item-documentation-link'>
                        <a class='label' href='${item.documentationUrl}' target='_blank'>Documentation</a>
                    </div>
                    `
                        : ''
                    return `
                        <div class='list-item' data-name='${item.name}'>
                            <div class='list-content'>
                                <b class='list-item-name'>${item.name}</b>
                                <div class='list-item-description'>${item.description}</div>
                                ${documentationLink}
                            </div>
                            <label class="switch">
                                <input class='checkbox-${index}' type="checkbox" ${checked ? 'checked' : ''}>
                                <span class="slider round"></span>
                            </label>
                        </div>
                    `
                })
                .join('')
        }
        return ''
    }
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
            "key": "selector",
            "label": "Selector",
            "description": 'CSS selector to activate on. For example: "#my-beta-button" or "[data-attr=\'posthog-early-access-features-button\']"',
            "type": "string",
            "default": "",
        },
        {
            "key": "useButton",
            "label": "Show features button on the page",
            "description": "If enabled, a button will be shown on the page that will open the features modal.",
            "type": "choice",
            "choices": [
                {
                    "label": "Yes",
                    "value": "Yes",
                },
                {
                    "label": "No",
                    "value": "No",
                },
            ],
            "default": "No",
        },
    ],
)
