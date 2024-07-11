from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-aws-kinesis",
    name="AWS Kinesis",
    description="Put data to an AWS Kinesis stream",
    # icon_url="/api/projects/@current/hog_functions/icon/?id=posthog.com&temp=true",
    hog="""
fetch(inputs.url, {
  'headers': inputs.headers,
  'body': inputs.body,
  'method': inputs.method
});
""".strip(),
    inputs_schema=[
        {
            "key": "aws_access_key_id",
            "type": "string",
            "label": "AWS Access Key ID",
            "secret": True,
            "required": True,
        },
        {
            "key": "aws_secret_access_key",
            "type": "string",
            "label": "AWS Secret Access Key",
            "secret": True,
            "required": True,
        },
        {
            "key": "aws_kinesis_stream_arn",
            "type": "string",
            "label": "Kinesis Stream ARN",
            "secret": False,
            "required": False,
        },
        {
            "key": "payload",
            "type": "json",
            "label": "Message Payload",
            "default": {"event": "{event}", "person": "{person}"},
            "secret": False,
            "required": False,
        },
    ],
)
