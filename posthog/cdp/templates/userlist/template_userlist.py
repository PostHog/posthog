from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-userlist",
    name="Userlist",
    description="Send user, company, and event data to Userlist",
    icon_url="/static/services/userlist.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
let base_uri := 'https://incoming.userlist.com/posthog'

fun compact(obj) {
    let result := {}

    for (let key, value in obj) {
        if (value != null) {
            result[key] := value
        }
    }

    return result
}

fun push(endpoint, body) {
    if (empty(body)) {
        print('Error sending data to Userlist: Invalid payload')
        return
    }

    let res := fetch(f'{base_uri}{endpoint}', {
        'method': 'POST',
        'headers': {
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json',
            'Authorization': f'Push {inputs.push_key}',
        },
        'body': body
    })

    if (res.status >= 400) {
        print(f'Error sending data to Userlist: {res.status} - {res.body}')
    }

    return res
}

let user_payload := compact({
    'identifier': inputs.user_identifier,
    'email': inputs.user_email,
    'properties': compact(inputs.user_properties)
})

if (empty(user_payload.identifier) and empty(user_payload.email)) {
    user_payload := null
}

let company_payload := compact({
    'identifier': inputs.company_identifier,
    'name': inputs.company_name,
    'properties': compact(inputs.company_properties),
})

if (empty(company_payload.identifier)) {
    company_payload := null
}

let event_payload := compact({
    'name': event.event,
    'user': user_payload,
    'company': company_payload,
    'occurred_at': event.timestamp,
    'properties': compact(event.properties)
})

if (empty(event_payload.name) or (empty(event_payload.user) and empty(event_payload.company))) {
    event_payload := null
}

if (event.event in ['$identify', '$set']) {
    push('/users', user_payload)
} else if (event.event == '$groupidentify') {
    if (not empty(company_payload) and not empty(user_payload)) {
        company_payload.user := user_payload
    }

    push('/companies', company_payload)
} else if (match(event.event, '^[a-z][a-z0-9_-]*$')) {
    push('/events', event_payload)
} else {
    print(f'Skipping event {event.event} as it is not supported.')
    return
}
""".strip(),
    inputs_schema=[
        {
            "key": "push_key",
            "type": "string",
            "label": "Push Key",
            "description": "You can find your Push Key in your [Userlist Push settings](https://app.userlist.com/settings/push)",
            "secret": True,
            "required": True,
        },
        {
            "key": "user_identifier",
            "type": "string",
            "label": "User Identifier",
            "description": "The unique identifier for the user in Userlist.",
            "default": "{person.id}",
            "required": True,
        },
        {
            "key": "user_email",
            "type": "string",
            "label": "User Email",
            "description": "The email address of the user.",
            "default": "{person.properties.email}",
        },
        {
            "key": "user_properties",
            "type": "dictionary",
            "label": "Custom User Properties",
            "description": "Map of custom user properties and their values.",
            "default": {
                "lastname": "{person.properties.lastname ?? person.properties.lastName ?? person.properties.last_name}",
                "firstname": "{person.properties.firstname ?? person.properties.firstName ?? person.properties.first_name}",
            },
        },
        {
            "key": "company_identifier",
            "type": "string",
            "label": "Company Identifier",
            "description": "The unique identifier for the company in Userlist.",
            "default": "{groups.account.id}",
        },
        {
            "key": "company_name",
            "type": "string",
            "label": "Company Name",
            "description": "The name of the company.",
            "default": "{groups.account.properties.name}",
        },
        {
            "key": "company_properties",
            "type": "dictionary",
            "label": "Custom Company Properties",
            "description": "Map of custom company properties and their values.",
            "default": {
                "industry": "{groups.account.properties.industry}",
            },
        },
    ],
    filters={
        "events": [
            {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
            {"id": "$set", "name": "$set", "type": "events", "order": 1},
            {"id": "$groupidentify", "name": "$groupidentify", "type": "events", "order": 2},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)
