from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.aws_kinesis.template_aws_kinesis import template as template_aws_kinesis


class TestTemplateAwsKinesis(BaseHogFunctionTemplateTest):
    template = template_aws_kinesis

    def test_function_works(self):
        res = self.run_function(
            inputs={
                "aws_access_key_id": "aws_access_key_id",
                "aws_secret_access_key": "aws_secret_access_key",
                "aws_kinesis_stream_arn": "aws_kinesis_stream_arn",
                "payload": {"hello": "world"},
            }
        )

        assert res.result is None

        assert self.get_mock_fetch_calls()[0] == (
            "https://posthog.com",
            {
                "headers": {},
                "body": {"hello": "world"},
                "method": "GET",
            },
        )
