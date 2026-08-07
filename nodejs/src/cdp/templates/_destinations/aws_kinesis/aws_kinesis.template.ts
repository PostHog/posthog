import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: false,
    type: 'destination',
    id: 'template-aws-kinesis',
    name: 'AWS Kinesis',
    description: 'Put data to an AWS Kinesis stream',
    icon_url: '/static/services/aws-kinesis.png',
    category: ['Analytics'],
    code_language: 'hog',
    code: `
let payload := jsonStringify({
  'StreamName': inputs.aws_kinesis_stream_name,
  'PartitionKey': inputs.aws_kinesis_partition_key ?? generateUUIDv4(),
  'Data': base64Encode(jsonStringify(inputs.payload)),
})

let res := fetch(f'https://kinesis.{inputs.aws_region}.amazonaws.com', {
  'method': 'POST',
  'headers': {
    'Content-Type': 'application/x-amz-json-1.1',
    'X-Amz-Target': 'Kinesis_20131202.PutRecord',
  },
  'body': payload,
  'aws_sigv4': {
    'service': 'kinesis',
    'region': inputs.aws_region,
    'access_key_id_input': 'aws_access_key_id',
    'secret_access_key_input': 'aws_secret_access_key',
  },
})

if (res.status >= 200 and res.status < 300) {
  print('Event sent successfully!')
} else {
  throw Error(f'Error from {inputs.aws_region}.amazonaws.com (status {res.status}): {res.body}')
}
`.trim(),
    inputs_schema: [
        {
            key: 'aws_access_key_id',
            type: 'string',
            label: 'AWS Access Key ID',
            secret: true,
            required: true,
        },
        {
            key: 'aws_secret_access_key',
            type: 'string',
            label: 'AWS Secret Access Key',
            secret: true,
            required: true,
        },
        {
            key: 'aws_region',
            type: 'string',
            label: 'AWS Region',
            secret: false,
            required: true,
            default: 'us-east-1',
        },
        {
            key: 'aws_kinesis_stream_name',
            type: 'string',
            label: 'Kinesis Stream Name',
            secret: false,
            required: true,
        },
        {
            key: 'aws_kinesis_partition_key',
            type: 'string',
            label: 'Kinesis Partition Key',
            description: 'If not provided, a random UUID will be generated.',
            default: '{event.uuid}',
            secret: false,
            required: false,
        },
        {
            key: 'payload',
            type: 'json',
            label: 'Message Payload',
            default: {
                event: '{event}',
                person: '{person}',
            },
            secret: false,
            required: false,
        },
    ],
}
