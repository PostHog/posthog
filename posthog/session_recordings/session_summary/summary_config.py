import dataclasses
from typing import List


@dataclasses.dataclass(frozen=True)
class SessionRecordingSummaryConfig:
    opt_in: bool
    preferred_events: List[str]
    excluded_events: List[str]
    included_event_properties: List[str]

    @staticmethod
    def from_config_json(config_json: dict) -> "SessionRecordingSummaryConfig":
        raw_included_event_properties = config_json.get(
            "included_event_properties", ["elements_chain", "$window_id", "$current_url", "$event_type"]
        )
        included_event_properties = ["event", "timestamp"]
        for prop in raw_included_event_properties:
            if prop in ["elements_chain"]:
                included_event_properties.append(prop)
            else:
                included_event_properties.append(f"properties.{prop}")

        return SessionRecordingSummaryConfig(
            opt_in=config_json.get("opt_in", False),
            preferred_events=config_json.get("preferred_events", []),
            excluded_events=config_json.get("excluded_events", ["$feature_flag_called"]),
            included_event_properties=included_event_properties,
        )
