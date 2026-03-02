from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-stripe",
    name="Stripe warehouse source webhook",
    description="Receive Stripe webhook events for data warehouse ingestion",
    icon_url="/static/services/stripe.png",
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

if (not inputs.bypass_signature_check) {
  let body := request.stringBody
  let signatureHeader := request.headers['stripe-signature']

  if (empty(signatureHeader)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

  let headerParts := splitByString(',', signatureHeader)
  let timestamp := null
  let v1Signature := null

  for (let _, part in headerParts) {
      let trimmed := trim(part)
      if (trimmed like 't=%') {
          let tParts := splitByString('=', trimmed, 2)
          if (length(tParts) = 2) {
              timestamp := tParts[2]
          }
      }
      if (trimmed like 'v1=%') {
          let v1Parts := splitByString('=', trimmed, 2)
          if (length(v1Parts) = 2) {
              v1Signature := v1Parts[2]
          }
      }
  }

  if (empty(timestamp) or empty(v1Signature)) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Could not parse signature',
        }
      }
  }

  let signedPayload := concat(timestamp, '.', body)
  let computedSignature := sha256HmacChainHex([inputs.signing_secret, signedPayload])

  if (computedSignature != v1Signature) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Bad signature',
        }
      }
  }
}

return request.body""",
    inputs_schema=[
        {
            "type": "string",
            "key": "signing_secret",
            "label": "Signing secret",
            "required": False,
            "secret": True,
            "hidden": False,
            "description": "Used to validate the webhook came from Stripe",
        },
        {
            "type": "boolean",
            "key": "bypass_signature_check",
            "label": "Bypass signature check",
            "description": "If set, the stripe-signature header will not be checked. This is not recommended.",
            "default": False,
            "required": False,
            "secret": False,
        },
    ],
)
