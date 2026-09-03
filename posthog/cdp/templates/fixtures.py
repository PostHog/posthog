from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# The Slack destination itself lives in nodejs (nodejs/src/cdp/templates/_destinations/slack). Tests
# that need a real destination template in the database sync this stand-in instead of reaching out to
# the plugin server. It does not have to track the nodejs template field for field.
template_slack = HogFunctionTemplateDC(
    status="stable",
    free=True,
    type="destination",
    id="template-slack",
    name="Slack",
    description="Sends a message to a Slack channel",
    icon_url="/static/services/slack.png",
    category=["Customer Success"],
    code_language="hog",
    code="""
// Slack rejects the whole message if a block is longer than its limit, so shorten the content
// instead of losing the notification. See https://api.slack.com/reference/block-kit/blocks
let MAX_BLOCKS := 50;
let MAX_SECTION_TEXT := 3000;
let MAX_BUTTON_TEXT := 75;

fun clip(value, limit) {
  if (typeof(value) == 'string' and length(value) > limit) {
    return f'{substring(value, 1, limit - 1)}…';
  }
  return value;
}

fun clipText(node, limit) {
  if (typeof(node) == 'object' and typeof(node.text) == 'object') {
    node.text.text := clip(node.text.text, limit);
  }
}

let blocks := inputs.blocks;
if (typeof(blocks) == 'array') {
  let clipped := [];
  for (let block in blocks) {
    if (length(clipped) < MAX_BLOCKS) {
      clipText(block, MAX_SECTION_TEXT);
      for (let element in block.elements ?? []) {
        clipText(element, MAX_BUTTON_TEXT);
      }
      clipped := arrayPushBack(clipped, block);
    }
  }
  blocks := clipped;
}

let res := fetch('https://slack.com/api/chat.postMessage', {
  'body': {
    'channel': inputs.channel,
    'blocks': blocks,
    'text': inputs.text
  },
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.slack_workspace.access_token}',
    'Content-Type': 'application/json'
  }
});

if (res.status != 200 or res.body.ok == false) {
  throw Error(f'Failed to post message to Slack: {res.status}: {res.body}');
}
""".strip(),
    inputs_schema=[
        {
            "key": "slack_workspace",
            "type": "integration",
            "integration": "slack",
            "label": "Slack workspace",
            "requiredScopes": "channels:read groups:read chat:write chat:write.customize",
            "secret": False,
            "hidden": False,
            "required": True,
        },
        {
            "key": "channel",
            "type": "integration_field",
            "integration_key": "slack_workspace",
            "integration_field": "slack_channel",
            "label": "Channel to post to",
            "secret": False,
            "hidden": False,
            "required": True,
        },
        {
            "key": "blocks",
            "type": "json",
            "label": "Blocks",
            "secret": False,
            "required": False,
            "hidden": False,
        },
        {
            "key": "text",
            "type": "string",
            "label": "Plain text message",
            "secret": False,
            "required": False,
            "hidden": False,
        },
        {
            "key": "thread_ts",
            "type": "string",
            "label": "Reply in thread",
            "secret": False,
            "required": False,
            "hidden": False,
        },
    ],
)
