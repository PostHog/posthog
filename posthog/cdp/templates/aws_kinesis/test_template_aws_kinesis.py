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

        # The Hog template now hands signing off to the Node.js cyclotron fetch executor,
        # which re-signs on every attempt. The aws_sigv4 bag carries input-key references,
        # not credential values — the executor resolves them from HogFunction.inputs at
        # fetch time so secrets never enter the plaintext queue payload.
        assert res.result is None
        assert self.get_mock_fetch_calls()[0] == (
            "https://kinesis.aws_region.amazonaws.com",
            {
                "method": "POST",
                "headers": {
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": "Kinesis_20131202.PutRecord",
                },
                "body": '{"StreamName": "aws_kinesis_stream_arn", "PartitionKey": "1", "Data": "eyJoZWxsbyI6ICJ3b3JsZCJ9"}',
                "aws_sigv4": {
                    "service": "kinesis",
                    "region": "aws_region",
                    "access_key_id_input": "aws_access_key_id",
                    "secret_access_key_input": "aws_secret_access_key",
                },
            },
        )
