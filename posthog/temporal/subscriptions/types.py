import typing
import dataclasses

from ee.tasks.subscriptions.subscription_utils import DEFAULT_MAX_ASSET_COUNT


@dataclasses.dataclass
class FetchDueSubscriptionsActivityInputs:
    buffer_minutes: int = 15

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "buffer_minutes": self.buffer_minutes,
        }


@dataclasses.dataclass
class CreateExportAssetsInputs:
    subscription_id: int
    max_asset_count: int = DEFAULT_MAX_ASSET_COUNT
    previous_value: typing.Optional[str] = None


@dataclasses.dataclass
class CreateExportAssetsResult:
    exported_asset_ids: list[int]
    total_insight_count: int
    team_id: int = 0
    distinct_id: str = ""
    target_type: str = ""


@dataclasses.dataclass
class DeliverSubscriptionInputs:
    subscription_id: int
    exported_asset_ids: list[int]
    total_insight_count: int
    is_new_subscription_target: bool = False
    previous_value: typing.Optional[str] = None
    invite_message: typing.Optional[str] = None


@dataclasses.dataclass
class ProcessSubscriptionWorkflowInputs:
    subscription_id: int
    previous_value: typing.Optional[str] = None
    invite_message: typing.Optional[str] = None


@dataclasses.dataclass
class ScheduleAllSubscriptionsWorkflowInputs:
    buffer_minutes: int = 15

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "buffer_minutes": self.buffer_minutes,
        }
