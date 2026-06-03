from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-revenuecat",
    name="RevenueCat warehouse source webhook",
    description="Receive RevenueCat webhook events for data warehouse ingestion",
    icon_url="/static/services/revenuecat.png",
    category=["Data warehouse"],
    code_language="hog",
    code="""\
if (request.method != 'POST') {
  return {
    'httpResponse': {
      'status': 405,
      'body': 'Method not allowed'
    }
  }
}

if (not inputs.bypass_authorization_check) {
  if (empty(inputs.authorization_header)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Authorization header value not configured',
      }
    }
  }

  let providedHeader := request.headers['authorization']

  if (empty(providedHeader)) {
    return {
      'httpResponse': {
        'status': 401,
        'body': 'Missing authorization header',
      }
    }
  }

  if (providedHeader != inputs.authorization_header) {
    return {
      'httpResponse': {
        'status': 401,
        'body': 'Bad authorization header',
      }
    }
  }
}

let eventType := request.body.event?.type

if (empty(eventType)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'No event type found, skipping'
    }
  }
}

if (eventType = 'TEST') {
  return {
    'httpResponse': {
      'status': 200,
      'body': 'Test event acknowledged'
    }
  }
}

// RevenueCat funnels every event type into the single `events` warehouse table
// — the schema_mapping is keyed by a wildcard ("*") which we look up here.
let schemaId := inputs.schema_mapping?.['*']

if (empty(schemaId)) {
  return {
    'httpResponse': {
      'status': 200,
      'body': f'No schema mapping for event type: {eventType}, skipping'
    }
  }
}

produceToWarehouseWebhooks(request.body, schemaId)""",
    inputs_schema=[
        {
            "type": "string",
            "key": "authorization_header",
            "label": "Authorization header value",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": (
                "The exact value RevenueCat will send in the Authorization header "
                "(e.g. `Bearer my-secret`). PostHog rejects deliveries whose header does not match."
            ),
        },
        {
            "type": "boolean",
            "key": "bypass_authorization_check",
            "label": "Bypass authorization header check",
            "description": ("If set, the Authorization header will not be checked. This is not recommended."),
            "default": False,
            "required": False,
            "secret": False,
        },
        {
            "type": "json",
            "key": "schema_mapping",
            "label": "Schema mapping",
            "description": "Maps RevenueCat resource names to ExternalDataSchema IDs",
            "required": True,
            "secret": False,
            "hidden": True,
        },
        {
            "type": "string",
            "key": "source_id",
            "label": "Source ID",
            "description": "The ExternalDataSource ID this webhook is associated with",
            "required": True,
            "secret": False,
            "hidden": True,
        },
    ],
)
