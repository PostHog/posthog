from datetime import datetime, timedelta
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team.team import Team
from posthog.test.base import (
    _create_event,
    _create_person,
)
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    XDIST_SUFFIX,
)
import s3fs
from pyarrow import parquet as pq
import pyarrow as pa
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.table import DataWarehouseTable

TEST_BUCKET = "test_storage_bucket-posthog.hogql.experiments.queryrunner" + XDIST_SUFFIX


def create_data_warehouse_table(team: Team, table_name: str, table_data: list[dict], columns: dict[str, str]):
    if not OBJECT_STORAGE_ACCESS_KEY_ID or not OBJECT_STORAGE_SECRET_ACCESS_KEY:
        raise Exception("Missing vars")

    fs = s3fs.S3FileSystem(
        client_kwargs={
            "region_name": "us-east-1",
            "endpoint_url": OBJECT_STORAGE_ENDPOINT,
            "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
        },
    )

    path_to_s3_object = "s3://" + OBJECT_STORAGE_BUCKET + f"/{TEST_BUCKET}"

    pq.write_to_dataset(
        pa.Table.from_pylist(table_data),
        path_to_s3_object,
        filesystem=fs,
        use_dictionary=True,
        compression="snappy",
    )

    credential = DataWarehouseCredential.objects.create(
        access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
        access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
        team=team,
    )

    DataWarehouseTable.objects.create(
        name=table_name,
        url_pattern=f"http://host.docker.internal:19000/{OBJECT_STORAGE_BUCKET}/{TEST_BUCKET}/*.parquet",
        format=DataWarehouseTable.TableFormat.Parquet,
        team=team,
        columns=columns,
        credential=credential,
    )
    return table_name


def create_standard_group_test_events(team: Team, feature_flag: FeatureFlag):
    group_type_index: GroupTypeIndex = 0
    GroupTypeMapping.objects.create(
        team=team,
        project_id=team.project_id,
        group_type_index=group_type_index,
        group_type="organization",
    )

    # 7 groups, but two are unused
    for i in range(7):
        create_group(
            team_id=team.pk,
            group_type_index=group_type_index,
            group_key=f"org:{i}",
            properties={"name": f"org {i}"},
        )

    feature_flag_property = f"$feature/{feature_flag.key}"

    for variant, purchase_count in [("control", 6), ("test", 8)]:
        for i in range(22):
            _create_person(distinct_ids=[f"user_{variant}_{i}"], team_id=team.pk)
            # Assign each user to a group deterministically based on their index
            group_idx = 2 + (i % 3) if variant == "test" else i % 2
            _create_event(
                team=team,
                event="$feature_flag_called",
                distinct_id=f"user_{variant}_{i}",
                timestamp=datetime.now() + timedelta(hours=i),
                properties={
                    feature_flag_property: variant,
                    "$feature_flag_response": variant,
                    "$feature_flag": feature_flag.key,
                    "$group_0": f"org:{group_idx}",
                    "$groups": {
                        "organization": f"org:{group_idx}",
                    },
                },
            )
            if i < purchase_count:
                _create_event(
                    team=team,
                    event="purchase",
                    distinct_id=f"user_{variant}_{i}",
                    timestamp=datetime.now() + timedelta(hours=i + 1),
                    properties={
                        feature_flag_property: variant,
                        "$group_0": f"org:{group_idx}",
                        "$groups": {
                            "organization": f"org:{group_idx}",
                        },
                        "amount": 10 * i if i % 2 == 0 else "",
                    },
                )
