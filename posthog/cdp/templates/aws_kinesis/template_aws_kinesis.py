from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-aws-kinesis",
    name="AWS Kinesis",
    description="Put data to an AWS Kinesis stream",
    icon_url="/static/services/aws-kinesis.png",
    category=["Analytics"],
    code_language="hog",
    code="""
fun getPayload() {
  let region := inputs.aws_region
  let service := 'kinesis'
  let amzDate := formatDateTime(now(), '%Y%m%dT%H%i%sZ')
  let date := formatDateTime(now(), '%Y%m%d')

  let payload := jsonStringify({
    'StreamName': inputs.aws_kinesis_stream_name,
    'PartitionKey': inputs.aws_kinesis_partition_key ?? generateUUIDv4(),
    'Data': base64Encode(jsonStringify(inputs.payload)),
  })

  let requestHeaders := {
    'Content-Type': 'application/x-amz-json-1.1',
    'X-Amz-Target': 'Kinesis_20131202.PutRecord',
    'X-Amz-Date': amzDate,
    'Host': f'kinesis.{region}.amazonaws.com',
  }

  let canonicalHeaderParts := []
  for (let key, value in requestHeaders) {
    let val := replaceAll(trim(value), '\\\\s+', ' ')
    canonicalHeaderParts := arrayPushBack(canonicalHeaderParts, f'{lower(key)}:{val}')
  }
  let canonicalHeaders := arrayStringConcat(arraySort(canonicalHeaderParts), '\\n') || '\\n'

  let signedHeaderParts := []
  for (let key, value in requestHeaders) {
    signedHeaderParts := arrayPushBack(signedHeaderParts, lower(key))
  }
  let signedHeaders := arrayStringConcat(arraySort(signedHeaderParts), ';')

  let canonicalRequest := arrayStringConcat([
    'POST',
    '/',
    '',
    canonicalHeaders,
    signedHeaders,
    sha256Hex(payload),
  ], '\\n')

  let credentialScope := f'{date}/{region}/{service}/aws4_request'
  let stringToSign := arrayStringConcat([
    'AWS4-HMAC-SHA256',
    amzDate,
    credentialScope,
    sha256Hex(canonicalRequest),
  ], '\\n')

  let signature := sha256HmacChainHex([
    f'AWS4{inputs.aws_secret_access_key}', date, region, service, 'aws4_request', stringToSign
  ])

  let authorizationHeader :=
      f'AWS4-HMAC-SHA256 Credential={inputs.aws_access_key_id}/{credentialScope}, ' ||
      f'SignedHeaders={signedHeaders}, ' ||
      f'Signature={signature}'

  requestHeaders['Authorization'] := authorizationHeader

  return {
    'headers': requestHeaders,
    'body': payload,
    'method': 'POST'
  }
}

let res := fetch(f'https://kinesis.{inputs.aws_region}.amazonaws.com', getPayload())

if (res.status >= 200 and res.status < 300) {
  print('Event sent successfully!')
} else {
  throw Error(f'Error from {inputs.aws_region}.amazonaws.com (status {res.status}): {res.body}')
}
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
            "key": "aws_region",
            "type": "string",
            "label": "AWS Region",
            "secret": False,
            "required": True,
            "default": "us-east-1",
        },
        {
            "key": "aws_kinesis_stream_name",
            "type": "string",
            "label": "Kinesis Stream Name",
            "secret": False,
            "required": True,
        },
        {
            "key": "aws_kinesis_partition_key",
            "type": "string",
            "label": "Kinesis Partition Key",
            "description": "If not provided, a random UUID will be generated.",
            "default": "{event.uuid}",
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
