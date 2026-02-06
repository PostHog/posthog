from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-cursor-agent",
    name="Cursor",
    description="Launch a Cursor background agent to work on a repository",
    icon_url="/static/services/cursor.png",
    category=["Engineering"],
    code_language="hog",
    code="""
let base64Auth := base64Encode(f'{inputs.cursor_account.api_key}:')

if (empty(inputs.prompt)) {
    throw Error('Prompt cannot be empty. Configure the agent prompt in the workflow step.')
}

if (empty(inputs.repository)) {
    throw Error('Repository is required. Select a repository in the workflow step.')
}

let body := {
    'prompt': {
        'text': inputs.prompt
    },
    'source': {
        'repository': inputs.repository
    },
    'target': {
        'autoCreatePr': inputs.auto_create_pr
    }
}

if (not empty(inputs.ref)) {
    body.source.ref := inputs.ref
}

let res := fetch('https://api.cursor.com/v0/agents', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {base64Auth}',
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status >= 400) {
    let errorMessage := res.body?.message ?? res.body?.error ?? res.body ?? ''
    if (empty(errorMessage)) {
        errorMessage := '(no message from Cursor API; try again or check status.cursor.com)'
    }
    let codePart := if (res.body?.code != null) then f' [{res.body.code}]' else ''
    throw Error(f'Failed to launch Cursor agent: {res.status}{codePart}: {errorMessage}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "cursor_account",
            "type": "integration",
            "integration": "cursor",
            "label": "Cursor account",
            "secret": False,
            "required": True,
        },
        {
            "key": "repository",
            "type": "integration_field",
            "integration_key": "cursor_account",
            "integration_field": "cursor_repository",
            "label": "Repository",
            "description": "GitHub repository for the agent to work on",
            "secret": False,
            "required": True,
        },
        {
            "key": "prompt",
            "type": "string",
            "label": "Agent prompt",
            "description": "Instructions for the background agent",
            "default": "{event.properties.description}",
            "secret": False,
            "required": True,
            "templating": "hog",
        },
        {
            "key": "ref",
            "type": "string",
            "label": "Branch",
            "description": "Git branch to base work on (leave empty for default)",
            "default": "",
            "secret": False,
            "required": False,
        },
        {
            "key": "auto_create_pr",
            "type": "boolean",
            "label": "Auto-create PR",
            "default": True,
            "secret": False,
            "required": False,
        },
    ],
)
