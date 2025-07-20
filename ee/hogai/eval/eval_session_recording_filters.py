import pytest
from braintrust import EvalCase

from posthog.schema import (
    DurationType,
    FilterLogicalOperator,
    MaxInnerUniversalFiltersGroup,
    MaxOuterUniversalFiltersGroup,
    MaxRecordingUniversalFilters,
    PropertyOperator,
    RecordingDurationFilter,
    EventPropertyFilter,
    PersonPropertyFilter,
    RecordingOrder,
)
from products.replay.backend.max_tools import SearchSessionRecordingsTool
from braintrust_core.score import Scorer

from ee.hogai.utils.types import AssistantState
from .conftest import MaxEval
import json
from braintrust import Score
from deepdiff import DeepDiff


DUMMY_EXISTING_FILTERS = json.dumps(
    MaxRecordingUniversalFilters(
        date_from="-30d",
        date_to=None,
        filter_test_accounts=True,
        duration=[
            RecordingDurationFilter(
                key=DurationType.DURATION,
                operator=PropertyOperator.EXACT,
                value=60.0,
                type="recording",
            )
        ],
        filter_group=MaxOuterUniversalFiltersGroup(
            type=FilterLogicalOperator.AND_,
            values=[
                MaxInnerUniversalFiltersGroup(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        EventPropertyFilter(
                            key="$level",
                            value=["error"],
                            operator=PropertyOperator.EXACT,
                            type="event",
                        )
                    ],
                )
            ],
        ),
    ).model_dump_json()
)


class DidNotChangeExistingFilters(Scorer):
    def _name(self):
        return "did_not_change_existing_filters"

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if expected is None:
            return Score(name=self._name(), score=0, metadata={"description": "No expected value provided"})

        return Score(name=self._name(), score=1, metadata={"description": "Did not change existing filters"})


class FilterScorer(Scorer):
    def _name(self):
        return "recording_filter_scorer"

    def _run_eval_sync(self, output, expected=None, **kwargs):
        # Compare Pydantic models by their dictionary representation
        if expected is None or output is None:
            return Score(name=self._name(), score=0, metadata={"description": "No expected value provided"})

        # Convert both to dict for comparison, handling None cases
        output_dict = output.model_dump() if hasattr(output, "model_dump") else output
        expected_dict = expected.model_dump() if hasattr(expected, "model_dump") else expected

        diff = DeepDiff(
            expected_dict,
            output_dict,
            ignore_order=True,
            ignore_string_type_changes=True,
            ignore_string_case=True,
            ignore_numeric_type_changes=True,
        )

        if not diff:
            return Score(name=self._name(), score=1, metadata={"description": "Filters are correct", "diff": diff})
        else:
            return Score(name=self._name(), score=0, metadata={"description": "Filters are incorrect", "diff": diff})


@pytest.fixture
def call_search_session_recordings(demo_org_team_user):
    def callable(change: str) -> MaxRecordingUniversalFilters:
        """Call the SearchSessionRecordingsTool and return the generated filters."""
        tool = SearchSessionRecordingsTool()
        tool._context = {"current_filters": DUMMY_EXISTING_FILTERS}
        tool._team = demo_org_team_user[1]
        tool._user = demo_org_team_user[2]
        tool._config = {}
        tool._state = AssistantState(messages=[])

        # The tool returns a tuple of (message, filters)
        _, filters = tool._run_impl(change)
        return filters

    return callable


@pytest.mark.django_db
async def eval_session_recording_filters(call_search_session_recordings):
    await MaxEval(
        experiment_name="session_recording_filters",
        task=call_search_session_recordings,
        scores=[FilterScorer()],
        data=[
            EvalCase(
                input="Show me recordings where users in Germany signed up and had an ai error",
                expected=MaxRecordingUniversalFilters(
                    date_from="-30d",
                    date_to=None,
                    filter_test_accounts=True,
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    PersonPropertyFilter(
                                        key="$geoip_country_name",
                                        value=["Germany"],
                                        operator=PropertyOperator.EXACT,
                                        type="person",
                                    ),
                                    EventPropertyFilter(
                                        key="$signup",
                                        value=["true"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    ),
                                    EventPropertyFilter(
                                        key="$ai_error",
                                        value=["true"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    ),
                                    EventPropertyFilter(
                                        key="$level",
                                        value=["error"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    ),
                                ],
                            )
                        ],
                    ),
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION,
                            operator=PropertyOperator.EXACT,
                            value=60.0,
                            type="recording",
                        )
                    ],
                    order=RecordingOrder.START_TIME,
                ),
            ),
            EvalCase(
                input="Show me recordings where users converted or used an ai model named gpt4o",
                expected=MaxRecordingUniversalFilters(
                    date_from="-30d",
                    date_to=None,
                    filter_test_accounts=True,
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$level",
                                        value=["error"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    )
                                ],
                            ),
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.OR_,
                                values=[
                                    EventPropertyFilter(
                                        key="converted",
                                        value=["true"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    ),
                                    EventPropertyFilter(
                                        key="$ai_model",
                                        value=["gpt4o"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    ),
                                ],
                            ),
                        ],
                    ),
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION,
                            operator=PropertyOperator.EXACT,
                            value=60.0,
                            type="recording",
                        )
                    ],
                    order=RecordingOrder.START_TIME,
                ),
            ),
            EvalCase(
                input="Show recordings longer than 5 minutes",
                expected=MaxRecordingUniversalFilters(
                    date_from="-30d",
                    date_to=None,
                    filter_test_accounts=True,
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$level",
                                        value=["error"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    )
                                ],
                            )
                        ],
                    ),
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION,
                            operator=PropertyOperator.GT,
                            value=300.0,
                            type="recording",
                        )
                    ],
                    order=RecordingOrder.START_TIME,
                ),
            ),
            EvalCase(
                input="Show recordings with rage clicks or console errors",
                expected=MaxRecordingUniversalFilters(
                    date_from="-30d",
                    date_to=None,
                    filter_test_accounts=True,
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.OR_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$level",
                                        value=["error"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    ),
                                ],
                            ),
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$rageclick",
                                        value=["true"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    ),
                                ],
                            ),
                        ],
                    ),
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION,
                            operator=PropertyOperator.EXACT,
                            value=60,
                            type="recording",
                        )
                    ],
                    order=RecordingOrder.START_TIME,
                ),
            ),
            EvalCase(
                input="Find recordings with active time less than 30 seconds",
                expected=MaxRecordingUniversalFilters(
                    date_from="-30d",
                    date_to=None,
                    filter_test_accounts=True,
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="$level",
                                        value=["error"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    )
                                ],
                            )
                        ],
                    ),
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.ACTIVE_SECONDS,
                            operator=PropertyOperator.LT,
                            value=30,
                            type="recording",
                        ),
                        RecordingDurationFilter(
                            key=DurationType.DURATION,
                            operator=PropertyOperator.EXACT,
                            value=60,
                            type="recording",
                        ),
                    ],
                    order=RecordingOrder.START_TIME,
                ),
            ),
            EvalCase(
                input="Find recordings from the last 7 days with more than 10 console logs and more than 1000ms of active time",
                expected=MaxRecordingUniversalFilters(
                    date_from="-7d",
                    date_to=None,
                    filter_test_accounts=True,
                    filter_group=MaxOuterUniversalFiltersGroup(
                        type=FilterLogicalOperator.AND_,
                        values=[
                            MaxInnerUniversalFiltersGroup(
                                type=FilterLogicalOperator.AND_,
                                values=[
                                    EventPropertyFilter(
                                        key="console_log_count",
                                        value=[10],
                                        operator=PropertyOperator.GT,
                                        type="event",
                                    ),
                                    EventPropertyFilter(
                                        key="$level",
                                        value=["error"],
                                        operator=PropertyOperator.EXACT,
                                        type="event",
                                    ),
                                ],
                            ),
                        ],
                    ),
                    duration=[
                        RecordingDurationFilter(
                            key=DurationType.DURATION,
                            operator=PropertyOperator.EXACT,
                            value=60,
                            type="recording",
                        ),
                        RecordingDurationFilter(
                            key=DurationType.ACTIVE_SECONDS,
                            operator=PropertyOperator.GT,
                            value=1,
                            type="recording",
                        ),
                    ],
                    order=RecordingOrder.START_TIME,
                ),
            ),
        ],
    )
