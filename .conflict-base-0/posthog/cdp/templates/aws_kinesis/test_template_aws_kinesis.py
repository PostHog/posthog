from freezegun import freeze_time

from posthog.cdp.templates.aws_kinesis.template_aws_kinesis import template as template_aws_kinesis
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest


class TestTemplateAwsKinesis(BaseHogFunctionTemplateTest):
    template = template_aws_kinesis

    @freeze_time("2024-04-16T12:34:51Z")
    def test_function_works(self):
        res = self.run_function(
            inputs={
                "aws_access_key_id": "aws_access_key_id",
                "aws_secret_access_key": "aws_secret_access_key",
                "aws_region": "aws_region",
                "aws_kinesis_stream_name": "aws_kinesis_stream_arn",
                "aws_kinesis_partition_key": "1",
                "payload": {"hello": "world"},
            }
        )

        assert res.result is None
        assert self.get_mock_fetch_calls()[0] == (
            "https://kinesis.aws_region.amazonaws.com",
            {
                "headers": {
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": "Kinesis_20131202.PutRecord",
                    "X-Amz-Date": "20240416T123451Z",
                    "Host": "kinesis.aws_region.amazonaws.com",
                    "Authorization": "AWS4-HMAC-SHA256 Credential=aws_access_key_id/20240416/aws_region/kinesis/aws4_request, SignedHeaders=content-type;host;x-amz-date;x-amz-target, Signature=65b18913b42d8a7a1d33c0711da192d5a2e99eb79fb08ab3e5eefb6488b903ff",
                },
                "body": '{"StreamName": "aws_kinesis_stream_arn", "PartitionKey": "1", "Data": "eyJoZWxsbyI6ICJ3b3JsZCJ9"}',
                "method": "POST",
            },
        )
