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
)
from products.replay.backend.max_tools import SearchSessionRecordingsTool

from ee.hogai.utils.types import AssistantState
from .conftest import MaxEval
import json
from autoevals.partial import ScorerWithPartial
from braintrust import Score


class FilterScorer(ScorerWithPartial):
    def _name(self):
        return "recording_filter_scorer"

    def _run_eval_sync(self, output, expected=None, **kwargs):
        # Compare Pydantic models by their dictionary representation
        if expected is None:
            return Score(name=self._name(), score=0, metadata={"description": "No expected value provided"})

        # Convert both to dict for comparison, handling None cases
        output_dict = output.model_dump() if hasattr(output, "model_dump") else output
        expected_dict = expected.model_dump() if hasattr(expected, "model_dump") else expected

        if output_dict == expected_dict:
            return Score(name=self._name(), score=1, metadata={"description": "Filters are correct"})
        else:
            return Score(name=self._name(), score=0, metadata={"description": "Filters are incorrect"})


@pytest.fixture
def call_search_session_recordings(demo_org_team_user):
    def callable(change: str) -> MaxRecordingUniversalFilters:
        """Call the SearchSessionRecordingsTool and return the generated filters."""
        tool = SearchSessionRecordingsTool()
        # Initialize required attributes manually since we're not using the proper constructor
        tool._context = {
            "current_filters": json.dumps(
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
        }
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
                                        value=["error"],
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
                    order=None,
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
                    order=None,
                ),
            ),
            # EvalCase(
            #     input="Show recordings longer than 5 minutes",
            #     expected=MaxRecordingUniversalFilters(
            #         date_from="-30d",
            #         date_to=None,
            #         filter_test_accounts=True,
            #         filter_group={
            #             "type": "AND",
            #             "values": [
            #                 {
            #                     "type": "AND",
            #                     "values": [
            #                         {
            #                         }
            #                     ],
            #                 }
            #             ],
            #         },
            #         duration=[
            #             RecordingDurationFilter(
            #                 key=DurationType.DURATION,
            #                 operator=PropertyOperator.GT,
            #                 value=300.0,
            #                 type="recording",
            #             )
            #         ],
            #         order=None,
            #     ),
            # ),
            # EvalCase(
            #     input="Find recordings where users visited the pricing page and are from the US",
            #     expected=MaxRecordingUniversalFilters(
            #         date_from="-30d",
            #         date_to=None,
            #         filter_test_accounts=True,
            #         filter_group={
            #             "type": "AND",
            #             "values": [
            #                 {
            #                     "type": "AND",
            #                     "values": [
            #                         {
            #                             "id": "$pageview",
            #                             "name": "$pageview",
            #                             "type": "events",
            #                             "properties": [
            #                                 {
            #                                     "key": "$current_url",
            #                                     "value": ["pricing"],
            #                                     "operator": "icontains",
            #                                     "type": "event",
            #                                 }
            #                             ],
            #                         },
            #                         {
            #                             "key": "$geoip_country_code",
            #                             "value": ["US"],
            #                             "operator": "exact",
            #                             "type": "person",
            #                         },
            #                     ],
            #                 }
            #             ],
            #         },
            #         duration=[],
            #         order=None,
            #     ),
            # ),
            # EvalCase(
            #     input="Show recordings with rage clicks or console errors",
            #     expected=MaxRecordingUniversalFilters(
            #         date_from="-30d",
            #         date_to=None,
            #         filter_test_accounts=True,
            #         filter_group={
            #             "type": "OR",
            #             "values": [
            #                 {
            #                     "id": "$rageclick",
            #                     "name": "$rageclick",
            #                     "type": "events",
            #                 },
            #                 {
            #                     "key": "level",
            #                     "value": ["error"],
            #                     "operator": "exact",
            #                     "type": "log_entry",
            #                 },
            #             ],
            #         },
            #         duration=[RecordingDurationFilter(
            #             key=DurationType.ACTIVE_SECONDS,
            #             operator=PropertyOperator.LT,
            #             value=30,
            #             type="recording",
            #         )],
            #         order=None,
            #     ),
            # ),
            # EvalCase(
            #     input="Find recordings from mobile users who signed up",
            #     expected=MaxRecordingUniversalFilters(
            #         date_from="-30d",
            #         date_to=None,
            #         filter_test_accounts=True,
            #         filter_group={
            #             "type": "AND",
            #             "values": [
            #                 {
            #                     "type": "AND",
            #                     "values": [
            #                         {
            #                             "id": "signed_up",
            #                             "name": "signed_up",
            #                             "type": "events",
            #                         },
            #                         {
            #                             "key": "$device_type",
            #                             "value": ["mobile"],
            #                             "operator": "exact",
            #                             "type": "person",
            #                         },
            #                     ],
            #                 }
            #             ],
            #         },
            #         duration=[RecordingDurationFilter(
            #             key=DurationType.ACTIVE_SECONDS,
            #             operator=PropertyOperator.LT,
            #             value=30,
            #             type="recording",
            #         )],
            #         order=None,
            #     ),
            # ),
            # EvalCase(
            #     input="Show recordings with console warnings containing 'deprecated'",
            #     expected=MaxRecordingUniversalFilters(
            #         date_from="-30d",
            #         date_to=None,
            #         filter_test_accounts=True,
            #         filter_group={
            #             "type": "AND",
            #             "values": [
            #                 {
            #                     "type": "AND",
            #                     "values": [
            #                         {
            #                             "key": "level",
            #                             "value": ["warn"],
            #                             "operator": "exact",
            #                             "type": "log_entry",
            #                         },
            #                         {
            #                             "key": "message",
            #                             "value": ["deprecated"],
            #                             "operator": "icontains",
            #                             "type": "log_entry",
            #                         },
            #                     ],
            #                 }
            #             ],
            #         },
            #         duration=[RecordingDurationFilter(
            #             key=DurationType.ACTIVE_SECONDS,
            #             operator=PropertyOperator.LT,
            #             value=30,
            #             type="recording",
            #         )],
            #         order=None,
            #     ),
            # ),
            # EvalCase(
            #     input="Find recordings with active time less than 30 seconds",
            #     expected=MaxRecordingUniversalFilters(
            #         date_from="-30d",
            #         date_to=None,
            #         filter_test_accounts=True,
            #         filter_group={
            #             "type": "AND",
            #             "values": [
            #                 {
            #                     "type": "AND",
            #                     "values": [],
            #                 }
            #             ],
            #         },
            #         duration=[
            #             {
            #                 "key": "active_seconds",
            #                 "operator": "lt",
            #                 "value": 30,
            #                 "type": "recording",
            #             }
            #         ],
            #         order=None,
            #     ),
            # ),
            # EvalCase(
            #     input="Show recordings from users with email containing '@gmail.com' who visited the dashboard",
            #     expected=MaxRecordingUniversalFilters(
            #         date_from="-30d",
            #         date_to=None,
            #         filter_test_accounts=True,
            #         filter_group={
            #             "type": "AND",
            #             "values": [
            #                 {
            #                     "type": "AND",
            #                     "values": [
            #                         {
            #                             "id": "$pageview",
            #                             "name": "$pageview",
            #                             "type": "events",
            #                             "properties": [
            #                                 {
            #                                     "key": "$current_url",
            #                                     "value": ["dashboard"],
            #                                     "operator": "icontains",
            #                                     "type": "event",
            #                                 }
            #                             ],
            #                         },
            #                         {
            #                             "key": "email",
            #                             "value": ["@gmail.com"],
            #                             "operator": "icontains",
            #                             "type": "person",
            #                         },
            #                     ],
            #                 }
            #             ],
            #         },
            #         duration=[],
            #         order=None,
            #     ),
            # ),
            # EvalCase(
            #     input="Find recordings from the last 7 days with more than 10 console logs",
            #     expected=MaxRecordingUniversalFilters(
            #         date_from="-7d",
            #         date_to=None,
            #         filter_test_accounts=True,
            #         filter_group={
            #             "type": "AND",
            #             "values": [
            #                 {
            #                     "type": "AND",
            #                     "values": [
            #                         {
            #                             "key": "console_log_count",
            #                             "value": [10],
            #                             "operator": "gt",
            #                             "type": "recording",
            #                         }
            #                     ],
            #                 }
            #             ],
            #         },
            #         duration=[],
            #         order=None,
            #     ),
            # ),
            # EvalCase(
            #     input="Show recordings where users either clicked a button or submitted a form",
            #     expected=MaxRecordingUniversalFilters(
            #         date_from="-30d",
            #         date_to=None,
            #         filter_test_accounts=True,
            #         filter_group={
            #             "type": "OR",
            #             "values": [
            #                 {
            #                     "id": "$autocapture",
            #                     "name": "$autocapture",
            #                     "type": "events",
            #                     "properties": [
            #                         {
            #                             "key": "$el_tag_name",
            #                             "value": ["button"],
            #                             "operator": "exact",
            #                             "type": "event",
            #                         }
            #                     ],
            #                 },
            #                 {
            #                     "id": "$autocapture",
            #                     "name": "$autocapture",
            #                     "type": "events",
            #                     "properties": [
            #                         {
            #                             "key": "$el_tag_name",
            #                             "value": ["form"],
            #                             "operator": "exact",
            #                             "type": "event",
            #                         }
            #                     ],
            #                 },
            #             ],
            #         },
            #         duration=[],
            #         order=None,
            #     ),
            # ),
        ],
    )
