from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-slack",
    name="Slack warehouse source webhook",
    description="Receive Slack webhook events for data warehouse ingestion",
    icon_url="/static/services/slack.png",
    category=["Data warehouse"],
    code_language="hog",
    code="""\
if(request.method != 'POST') {
  return {
    'httpResponse': {
      'status': 405,
      'body': 'Method not allowed'
    }
  }
}

let body := request.body

if (not inputs.bypass_signature_check) {
  let rawBody := request.stringBody
  let slackSignature := request.headers['x-slack-signature']
  let slackTimestamp := request.headers['x-slack-request-timestamp']

  if (empty(slackSignature) or empty(slackTimestamp)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature headers',
      }
    }
  }

  let sigBasestring := concat('v0:', slackTimestamp, ':', rawBody)
  let computedSignature := concat('v0=', sha256HmacChainHex([inputs.signing_secret, sigBasestring]))

  if (computedSignature != slackSignature) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Bad signature',
      }
    }
  }
}

// Handle Slack URL verification challenge
if (body.type = 'url_verification') {
  return {
    'httpResponse': {
      'status': 200,
      'headers': {'Content-Type': 'application/json'},
      'body': jsonStringify({'challenge': body.challenge})
    }
  }
}

// Only process event_callback types
if (body.type = 'event_callback') {
  produceToWarehouseWebhooks(request.body)
}""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Signing secret",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": "Used to validate the webhook came from Slack. Found under Basic Information > App Credentials in your Slack app settings.",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the x-slack-signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "string",
            "key": "schema_id",
            "label": "Schema ID",
            "required": True,
            "description": "The ExternalDataSchema ID to link webhook data to.",
        },
        {
            "type": "string",
            "key": "source_type",
            "label": "Source type",
            "required": True,
            "description": "The source type for this webhook.",
        },
    ],
)
