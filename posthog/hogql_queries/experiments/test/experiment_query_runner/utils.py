from datetime import datetime, timedelta

from posthog.test.base import _create_event, _create_person

from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team.team import Team


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
