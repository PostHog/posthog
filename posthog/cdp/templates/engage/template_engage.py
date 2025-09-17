import dataclasses
from copy import deepcopy

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, HogFunctionTemplateMigrator

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-engage-so",
    name="Engage.so",
    description="Send events to Engage.so",
    icon_url="/static/services/engage.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
fetch('https://api.engage.so/posthog', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {base64Encode(f'{inputs.public_key}:{inputs.private_key}')}',
        'Content-Type': 'application/json'
    },
    'body': event
})
""".strip(),
    inputs_schema=[
        {
            "key": "public_key",
            "type": "string",
            "label": "Public key",
            "description": "Get your public key from your Engage dashboard (Settings -> Account)",
            "secret": True,
            "required": True,
        },
        {
            "key": "private_key",
            "type": "string",
            "label": "Private key",
            "description": "Get your private key from your Engage dashboard (Settings -> Account)",
            "secret": True,
            "required": True,
        },
    ],
    filters={
        "events": [
            {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
            {"id": "$set", "name": "$set", "type": "events", "order": 1},
            {"id": "$groupidentify", "name": "$groupidentify", "type": "events", "order": 2},
            {"id": "$unset", "name": "$unset", "type": "events", "order": 3},
            {"id": "$create_alias", "name": "$create_alias", "type": "events", "order": 4},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)


class TemplateEngageMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/posthog-engage-so-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))
        hf["hog"] = hf["code"]
        del hf["code"]

        public_key = obj.config.get("publicKey", "")
        private_key = obj.config.get("secret", "")

        hf["filters"] = {}

        hf["filters"]["events"] = [
            {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
            {"id": "$set", "name": "$set", "type": "events", "order": 1},
            {"id": "$groupidentify", "name": "$groupidentify", "type": "events", "order": 2},
            {"id": "$unset", "name": "$unset", "type": "events", "order": 3},
            {"id": "$create_alias", "name": "$create_alias", "type": "events", "order": 4},
        ]

        hf["inputs"] = {
            "public_key": {"value": public_key},
            "private_key": {"value": private_key},
        }

        return hf
