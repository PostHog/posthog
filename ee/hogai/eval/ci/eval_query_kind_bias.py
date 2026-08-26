"""Evals for query-kind selection under phrasing that pulls toward raw SQL.

The existing trends, funnel, and retention evals already score
``QueryKindSelection``, but their prompts name the analysis the agent should
reach for ("Show the $pageview trend"), so they cannot show the agent choosing
SQL over a typed query runner.

Every case here is answerable by a typed query runner, and phrased the way a
person asks when they are thinking in SQL: "count per day", "grouped by",
"count distinct", "of users who did X, how many then did Y". The odd phrasing
is the eval. Rewriting a prompt to name the analysis it wants removes the
pressure being measured, so keep prompts in the user's vocabulary rather than
PostHog's.

Scored on query kind alone. Whether the query is *correct* is already covered
by the per-kind evals; these cases only ask which runner the agent picked.

``eval_query_kind_bias_control`` runs the other direction, and the three suites
above are not readable without it. An agent that answers every question with a
trend scores full marks on them, which reads as "no bias" when it means "the
agent ignored the question". The control cases need row listings or per-row
window functions, which no typed runner can express, so SQL is the only correct
answer and a low control score means the typed suites are measuring nothing.
"""

import pytest

from braintrust import EvalCase

from posthog.schema import NodeKind

from ..base import MaxPublicEval
from ..scorers import QueryKindSelection

# "count per day", "grouped by", "count distinct", "average" — SQL vocabulary
# for aggregations that trends expresses as an interval, a breakdown, or a math
# operation on a property.
TRENDS_CASES = [
    EvalCase(
        input="Count uploaded_file events per day over the last 30 days",
        expected=NodeKind.TRENDS_QUERY,
    ),
    EvalCase(
        input="Write me a query showing the number of signed_up events per week over the last 8 weeks",
        expected=NodeKind.TRENDS_QUERY,
    ),
    EvalCase(
        input="Show downloaded_file events grouped by file_type over the last 30 days",
        expected=NodeKind.TRENDS_QUERY,
    ),
    EvalCase(
        input="What is the average file_size_b on uploaded_file events over the last 30 days?",
        expected=NodeKind.TRENDS_QUERY,
    ),
    EvalCase(
        input="Count distinct users who fired logged_in in the last 7 days",
        expected=NodeKind.TRENDS_QUERY,
    ),
]

# Step sequences, phrased as the self-join a person would write by hand.
FUNNEL_CASES = [
    EvalCase(
        input="Of users who fired signed_up, how many went on to fire uploaded_file within a week?",
        expected=NodeKind.FUNNELS_QUERY,
    ),
    EvalCase(
        input="How many people fired signed_up and then upgraded_plan over the last 30 days?",
        expected=NodeKind.FUNNELS_QUERY,
    ),
    EvalCase(
        input="What share of users who viewed /pricing/ went on to fire signed_up over the last 8 weeks?",
        expected=NodeKind.FUNNELS_QUERY,
    ),
]

# "Came back" and "still active" phrasing, which invites a cohort self-join.
RETENTION_CASES = [
    EvalCase(
        input="Of users who fired signed_up in the last 8 weeks, how many came back to fire logged_in in each of the following weeks?",
        expected=NodeKind.RETENTION_QUERY,
    ),
    EvalCase(
        input="For users whose first uploaded_file was in the last 8 weeks, how many were still uploading each week after?",
        expected=NodeKind.RETENTION_QUERY,
    ),
]


# Negative controls. Each needs raw rows or a per-row window function, neither
# of which trends, funnels, or retention can express — so there is no judgment
# call about whether SQL is right here.
CONTROL_CASES = [
    EvalCase(
        input="List the 10 largest files by file_size_b from uploaded_file, with their file_name",
        expected=NodeKind.HOG_QL_QUERY,
    ),
    EvalCase(
        input="For each account, show the first and last logged_in timestamp",
        expected=NodeKind.HOG_QL_QUERY,
    ),
    EvalCase(
        input="What is the median file_size_b on uploaded_file, and which accounts upload above it?",
        expected=NodeKind.HOG_QL_QUERY,
    ),
]


@pytest.mark.django_db
async def eval_query_kind_bias_trends(call_root_for_insight_generation, pytestconfig):
    await MaxPublicEval(
        experiment_name="query_kind_bias_trends",
        task=call_root_for_insight_generation,
        scores=[QueryKindSelection(expected=NodeKind.TRENDS_QUERY)],
        data=TRENDS_CASES,
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_query_kind_bias_funnel(call_root_for_insight_generation, pytestconfig):
    await MaxPublicEval(
        experiment_name="query_kind_bias_funnel",
        task=call_root_for_insight_generation,
        scores=[QueryKindSelection(expected=NodeKind.FUNNELS_QUERY)],
        data=FUNNEL_CASES,
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_query_kind_bias_retention(call_root_for_insight_generation, pytestconfig):
    await MaxPublicEval(
        experiment_name="query_kind_bias_retention",
        task=call_root_for_insight_generation,
        scores=[QueryKindSelection(expected=NodeKind.RETENTION_QUERY)],
        data=RETENTION_CASES,
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_query_kind_bias_control(call_root_for_insight_generation, pytestconfig):
    await MaxPublicEval(
        experiment_name="query_kind_bias_control",
        task=call_root_for_insight_generation,
        scores=[QueryKindSelection(expected=NodeKind.HOG_QL_QUERY)],
        data=CONTROL_CASES,
        pytestconfig=pytestconfig,
    )
