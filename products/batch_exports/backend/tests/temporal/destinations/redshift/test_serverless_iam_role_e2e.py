import os
import json
import uuid
import asyncio
import datetime as dt
from collections.abc import AsyncIterator

import pytest

from django.conf import settings

import aioboto3
import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.models.integration import Integration
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.service import BatchExportInsertInputs, BatchExportModel
from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    ConnectionParameters,
    RedshiftInsertInputs,
    TableParameters,
    insert_into_redshift_activity_from_stage,
    redshift_default_fields,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    pytest.mark.skipif(
        os.getenv("REDSHIFT_SERVERLESS_TEST") != "1",
        reason="Set REDSHIFT_SERVERLESS_TEST=1 to create real Redshift Serverless resources.",
    ),
]


@pytest.fixture
def aws_region() -> str:
    return os.getenv("AWS_REGION", "us-east-1")


@pytest.fixture
def resource_prefix() -> str:
    return os.getenv("REDSHIFT_SERVERLESS_TEST_PREFIX", f"posthog-test-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def redshift_database() -> str:
    return "dev"


@pytest.fixture
def redshift_schema() -> str:
    return "public"


@pytest.fixture
def posthog_external_role_arn() -> str:
    role_arn = settings.BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN
    if not role_arn:
        pytest.skip("Set BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN to the PostHog role used for customer role assumption.")
    return role_arn


@pytest_asyncio.fixture
async def redshift_live_team(db) -> AsyncIterator[Team]:
    organization = await sync_to_async(Organization.objects.create)(
        name="Redshift serverless test org",
        is_ai_data_processing_approved=True,
    )
    team = await sync_to_async(Team.objects.create)(organization=organization, name="Redshift serverless test team")

    yield team

    await sync_to_async(team.delete)()
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def redshift_iam_role_arn(
    aws_region: str,
    resource_prefix: str,
    redshift_live_team: Team,
    posthog_external_role_arn: str,
) -> AsyncIterator[str]:
    role_name = f"{resource_prefix}-role"
    policy_name = f"{resource_prefix}-policy"
    external_id = f"posthog-{redshift_live_team.organization_id}"
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": posthog_external_role_arn},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"sts:ExternalId": external_id}},
            }
        ],
    }
    permissions_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["redshift-serverless:GetCredentials", "redshift-serverless:GetWorkgroup"],
                "Resource": "*",
            }
        ],
    }

    async with aioboto3.Session().client("iam", region_name=aws_region) as client:
        response = await client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Temporary role for PostHog Redshift Serverless batch export tests",
            MaxSessionDuration=3600,
        )
        await client.put_role_policy(
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=json.dumps(permissions_policy),
        )

        try:
            yield response["Role"]["Arn"]
        finally:
            await client.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
            await client.delete_role(RoleName=role_name)


async def _wait_for_workgroup(client, workgroup_name: str) -> None:
    for _ in range(60):
        response = await client.get_workgroup(workgroupName=workgroup_name)
        if response["workgroup"]["status"] == "AVAILABLE":
            return
        await asyncio.sleep(10)
    raise TimeoutError(f"Timed out waiting for Redshift Serverless workgroup '{workgroup_name}'")


@pytest_asyncio.fixture
async def redshift_security_group(aws_region: str, resource_prefix: str) -> AsyncIterator[str]:
    group_name = f"{resource_prefix}-sg"

    async with aioboto3.Session().client("ec2", region_name=aws_region) as client:
        vpcs_response = await client.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])
        if not vpcs_response["Vpcs"]:
            pytest.skip("The live Redshift Serverless test requires a default VPC in the selected AWS region.")
        vpc_id = vpcs_response["Vpcs"][0]["VpcId"]

        response = await client.create_security_group(
            GroupName=group_name,
            Description="Temporary security group for PostHog Redshift Serverless batch export tests",
            VpcId=vpc_id,
        )
        group_id = response["GroupId"]
        await client.authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 5439,
                    "ToPort": 5439,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "Temporary Redshift test access"}],
                }
            ],
        )

        try:
            yield group_id
        finally:
            await client.delete_security_group(GroupId=group_id)


@pytest_asyncio.fixture
async def redshift_serverless_workgroup(
    aws_region: str, resource_prefix: str, redshift_security_group: str
) -> AsyncIterator[dict[str, str | int]]:
    namespace_name = f"{resource_prefix}-ns"
    workgroup_name = f"{resource_prefix}-wg"

    async with (
        aioboto3.Session().client("ec2", region_name=aws_region) as ec2_client,
        aioboto3.Session().client("redshift-serverless", region_name=aws_region) as client,
    ):
        vpcs_response = await ec2_client.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])
        if not vpcs_response["Vpcs"]:
            pytest.skip("The live Redshift Serverless test requires a default VPC in the selected AWS region.")
        subnets_response = await ec2_client.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpcs_response["Vpcs"][0]["VpcId"]]}]
        )
        subnet_ids = [subnet["SubnetId"] for subnet in subnets_response["Subnets"]]
        if len(subnet_ids) < 3:
            pytest.skip("The live Redshift Serverless test requires at least three default VPC subnets.")

        await client.create_namespace(namespaceName=namespace_name, dbName="dev")
        try:
            await client.create_workgroup(
                workgroupName=workgroup_name,
                namespaceName=namespace_name,
                publiclyAccessible=True,
                baseCapacity=8,
                securityGroupIds=[redshift_security_group],
                subnetIds=subnet_ids,
            )
            await _wait_for_workgroup(client, workgroup_name)
            workgroup = (await client.get_workgroup(workgroupName=workgroup_name))["workgroup"]
            endpoint = workgroup["endpoint"]
            yield {
                "workgroup_name": workgroup_name,
                "host": endpoint["address"],
                "port": int(endpoint.get("port", 5439)),
            }
        finally:
            await client.delete_workgroup(workgroupName=workgroup_name)
            await _wait_for_workgroup_deleted(client, workgroup_name)
            await client.delete_namespace(namespaceName=namespace_name)


async def _wait_for_workgroup_deleted(client, workgroup_name: str) -> None:
    for _ in range(60):
        try:
            await client.get_workgroup(workgroupName=workgroup_name)
        except Exception:
            return
        await asyncio.sleep(10)
    raise TimeoutError(f"Timed out waiting for Redshift Serverless workgroup '{workgroup_name}' deletion")


async def test_insert_into_redshift_activity_with_serverless_iam_role(
    clickhouse_client,
    activity_environment,
    redshift_serverless_workgroup,
    redshift_database,
    redshift_schema,
    redshift_iam_role_arn,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    redshift_live_team,
) -> None:
    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=redshift_live_team.pk,
        event_name="test-redshift-serverless-{i}",
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10,
    )

    integration = await Integration.objects.acreate(
        team_id=redshift_live_team.pk,
        kind=Integration.IntegrationKind.REDSHIFT,
        integration_id="serverless-prod",
        config={
            "name": "serverless-prod",
            "authentication_type": "iam_role",
            "aws_role_arn": redshift_iam_role_arn,
        },
    )

    batch_export_id = str(uuid.uuid4())
    batch_export_inputs = BatchExportInsertInputs(
        team_id=redshift_live_team.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=BatchExportModel(name="events", schema=None),
        batch_export_id=batch_export_id,
        destination_default_fields=redshift_default_fields(),
    )
    stage_result = await activity_environment.run(
        insert_into_internal_stage_activity,
        BatchExportInsertIntoInternalStageInputs(
            team_id=redshift_live_team.pk,
            batch_export_id=batch_export_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            batch_export_model=BatchExportModel(name="events", schema=None),
            destination_default_fields=redshift_default_fields(),
        ),
    )
    batch_export_inputs.stage_folder = stage_result.stage_folder
    batch_export_inputs.records_total = stage_result.records_total
    table_name = f"serverless_iam_{redshift_live_team.pk}_{dt.datetime.now(dt.UTC).strftime('%H%M%S')}"

    result = await activity_environment.run(
        insert_into_redshift_activity_from_stage,
        RedshiftInsertInputs(
            batch_export=batch_export_inputs,
            connection=ConnectionParameters(database=redshift_database, integration_id=integration.id),
            table=TableParameters(schema_name=redshift_schema, name=table_name),
        ),
    )

    assert result.error is None
    assert result.records_completed is not None and result.records_completed > 0
