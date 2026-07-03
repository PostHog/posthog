from unittest.mock import patch

from parameterized import parameterized

from ee.sqs.SQSProducer import SQSProducer


class TestSQSProducer:
    @parameterized.expand([("none_region", None), ("empty_region", "")])
    @patch("ee.sqs.SQSProducer.boto3.client")
    def test_falsy_region_falls_back_to_default(self, _name, region, mock_boto_client):
        # A None/empty region (e.g. an unset SQS_*_REGION env var) must not reach boto3,
        # which raises NoRegionError on a falsy region_name.
        SQSProducer(queue_url="https://example.com/queue", region_name=region)

        assert mock_boto_client.call_args.kwargs["region_name"] == "us-east-1"

    @patch("ee.sqs.SQSProducer.boto3.client")
    def test_explicit_region_is_passed_through(self, mock_boto_client):
        SQSProducer(queue_url="https://example.com/queue", region_name="eu-west-1")

        assert mock_boto_client.call_args.kwargs["region_name"] == "eu-west-1"
