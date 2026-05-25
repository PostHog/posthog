# ruff: noqa: T201 allow print statements
"""Seed demo Survey models + corresponding `survey sent` events.

Run as part of `generate_demo_data` so a fresh demo project always has a few
surveys to explore — with multi-question variety and responses tied to the
real simulated personas (not synthetic `respondent-N` distinct ids)."""

import uuid
import random
import datetime as dt
from collections.abc import Callable
from typing import Any

from posthog.models.event.util import create_event
from posthog.models.team.team import Team
from posthog.models.user import User

from products.surveys.backend.models import Survey

from .matrix import Matrix


def _nps_score(rng: random.Random) -> int:
    # Slightly promoter-skewed NPS for a healthy-but-realistic look
    return rng.choices(list(range(11)), weights=[1, 1, 1, 2, 2, 3, 5, 7, 12, 18, 18], k=1)[0]


def _csat5_positive(rng: random.Random) -> int:
    return rng.choices([1, 2, 3, 4, 5], weights=[2, 3, 8, 18, 22], k=1)[0]


def _csat5_onboarding(rng: random.Random) -> int:
    return rng.choices([1, 2, 3, 4, 5], weights=[1, 2, 7, 14, 12], k=1)[0]


_PLAN_CHOICES = ["Free", "Personal Pro", "Business", "Enterprise"]
_FEATURE_CHOICES = ["File upload", "Folder sharing", "Mobile app", "Search", "Version history", "Tags"]
_SOURCE_CHOICES = ["Friend or colleague", "Search engine", "Social media", "Podcast or blog", "Other"]

_OPEN_FEEDBACK = [
    "Faster uploads would help.",
    "Love the product, keep it up!",
    "Need a better mobile experience.",
    "Sharing links should support expiry.",
    "Folder colors please!",
    "Great service overall.",
    "Search results could be smarter.",
    "I would pay more for AI tagging.",
    "Sometimes the sync is slow.",
    "No complaints, works great.",
    "Add SSO for Business plan.",
    "Notifications are too noisy.",
]
_ONBOARDING_FEEDBACK = [
    "Took me a while to find folder sharing.",
    "The email verification email landed in spam.",
    "Wish the trial was longer.",
    "Pricing page could be clearer.",
    "Everything was smooth!",
    "I did not understand the file size limit.",
    "The mobile app prompt felt pushy.",
]


def _build_survey_specs(rng: random.Random) -> list[dict[str, Any]]:
    # IDs need to be stable per spec instance so the question id and the
    # response key (`$survey_response_<qid>`) match.
    q_nps = str(uuid.uuid4())
    q_csat = str(uuid.uuid4())
    q_plan = str(uuid.uuid4())
    q_features = str(uuid.uuid4())
    q_open = str(uuid.uuid4())
    q_link = str(uuid.uuid4())

    q_onb_rating = str(uuid.uuid4())
    q_onb_source = str(uuid.uuid4())
    q_onb_open = str(uuid.uuid4())

    response_fns: dict[str, Callable[[], Any]] = {
        q_nps: lambda: _nps_score(rng),
        q_csat: lambda: _csat5_positive(rng),
        q_plan: lambda: rng.choices(_PLAN_CHOICES, weights=[40, 25, 20, 5], k=1)[0],
        q_features: lambda: rng.sample(_FEATURE_CHOICES, k=rng.randint(1, 4)),
        q_open: lambda: rng.choice(_OPEN_FEEDBACK),
        q_link: lambda: "link clicked",
        q_onb_rating: lambda: _csat5_onboarding(rng),
        q_onb_source: lambda: rng.choices(_SOURCE_CHOICES, weights=[20, 30, 15, 10, 5], k=1)[0],
        q_onb_open: lambda: rng.choice(_ONBOARDING_FEEDBACK),
    }

    return [
        {
            "name": "Quarterly product feedback",
            "description": "Help us understand how Hedgebox is working for you.",
            "questions": [
                {
                    "id": q_nps,
                    "type": "rating",
                    "question": "How likely are you to recommend Hedgebox to a friend or colleague?",
                    "display": "number",
                    "scale": 10,
                    "lowerBoundLabel": "Not at all likely",
                    "upperBoundLabel": "Extremely likely",
                    "isNpsQuestion": True,
                },
                {
                    "id": q_csat,
                    "type": "rating",
                    "question": "How satisfied are you with Hedgebox overall?",
                    "display": "emoji",
                    "scale": 5,
                    "lowerBoundLabel": "Very unsatisfied",
                    "upperBoundLabel": "Very satisfied",
                },
                {
                    "id": q_plan,
                    "type": "single_choice",
                    "question": "Which plan are you on?",
                    "choices": _PLAN_CHOICES,
                    "shuffleOptions": False,
                    "hasOpenChoice": False,
                },
                {
                    "id": q_features,
                    "type": "multiple_choice",
                    "question": "Which features do you use most?",
                    "choices": _FEATURE_CHOICES,
                    "shuffleOptions": False,
                    "hasOpenChoice": False,
                },
                {
                    "id": q_open,
                    "type": "open",
                    "question": "What is one thing we could do better?",
                    "optional": True,
                },
                {
                    "id": q_link,
                    "type": "link",
                    "question": "Want to chat with our product team?",
                    "description": "Book a 30-minute call to share your feedback in depth.",
                    "link": "https://calendly.com/hedgebox/product-feedback",
                    "buttonText": "Book a call",
                    "optional": True,
                },
            ],
            "n_responses": 80,
            "response_fns": response_fns,
            "optional_question_ids": {q_open, q_link},
        },
        {
            "name": "Onboarding experience",
            "description": "A quick post-signup pulse check.",
            "questions": [
                {
                    "id": q_onb_rating,
                    "type": "rating",
                    "question": "How would you rate your onboarding experience?",
                    "display": "number",
                    "scale": 5,
                    "lowerBoundLabel": "Terrible",
                    "upperBoundLabel": "Excellent",
                },
                {
                    "id": q_onb_source,
                    "type": "single_choice",
                    "question": "How did you hear about Hedgebox?",
                    "choices": _SOURCE_CHOICES,
                    "shuffleOptions": False,
                    "hasOpenChoice": True,
                },
                {
                    "id": q_onb_open,
                    "type": "open",
                    "question": "Anything that confused you during signup?",
                    "optional": True,
                },
            ],
            "n_responses": 45,
            "response_fns": response_fns,
            "optional_question_ids": {q_onb_open},
        },
    ]


def _collect_respondents(matrix: Matrix) -> list[tuple[str, dict[str, Any]]]:
    """Walk the matrix and pull (distinct_id, person_properties) for every
    identified, active persona — those with at least one `distinct_id_at_now`
    and a real first/last seen window. Persons whose simulation never reached
    `now` (and so never took a snapshot) are skipped via `getattr` rather than
    crashing."""
    pool: list[tuple[str, dict[str, Any]]] = []
    for cluster in matrix.clusters:
        for person_row in cluster.people_matrix:
            for person in person_row:
                distinct_ids = getattr(person, "distinct_ids_at_now", None)
                if not distinct_ids or person.first_seen_at is None:
                    continue
                # Prefer the longest distinct_id (usually the in-product id assigned post-identify)
                distinct_id = max(distinct_ids, key=len)
                properties = getattr(person, "properties_at_now", None) or {}
                pool.append((distinct_id, dict(properties)))
    return pool


def seed_demo_surveys(
    matrix: Matrix,
    team: Team,
    creator: User,
    *,
    now: dt.datetime,
    response_window_days: int = 14,
) -> None:
    """Create demo surveys for `team` and emit realistic `survey sent` events
    using personas drawn from the matrix.

    Idempotent on the Survey rows (matched by `(team, name)`); events are
    appended on every run. Failures are logged and swallowed so a survey seed
    bug never breaks the rest of `generate_demo_data`."""
    rng = random.Random(f"survey-seed-{team.id}")
    respondents = _collect_respondents(matrix)
    if not respondents:
        print("No matrix personas available to act as survey respondents — skipping survey seeding.")
        return

    specs = _build_survey_specs(rng)
    for spec in specs:
        survey, was_new = Survey.objects.get_or_create(
            team=team,
            name=spec["name"],
            defaults={
                "description": spec["description"],
                "type": Survey.SurveyType.POPOVER,
                "questions": spec["questions"],
                "created_by": creator,
                "start_date": now - dt.timedelta(days=21),
                "schedule": Survey.Schedule.ALWAYS,
            },
        )
        if not was_new:
            print(f"  Survey '{survey.name}' already exists — appending responses.")

        sample_size = min(spec["n_responses"], len(respondents))
        chosen = rng.sample(respondents, sample_size)
        for distinct_id, person_properties in chosen:
            ts = now - dt.timedelta(
                days=rng.uniform(0, response_window_days),
                hours=rng.uniform(0, 24),
            )
            props: dict[str, Any] = {
                "$survey_id": str(survey.id),
                "$survey_name": survey.name,
                "$survey_submission_id": str(uuid.uuid4()),
                "$survey_questions": [{"id": q["id"], "question": q["question"]} for q in spec["questions"]],
            }
            for q in spec["questions"]:
                qid = q["id"]
                response_fn = spec["response_fns"].get(qid)
                if response_fn is None:
                    continue
                # Drop ~25% of optional question responses to mimic partial completions
                if qid in spec["optional_question_ids"] and rng.random() < 0.25:
                    continue
                props[f"$survey_response_{qid}"] = response_fn()
            create_event(
                event_uuid=uuid.uuid4(),
                event="survey sent",
                team=team,
                distinct_id=distinct_id,
                timestamp=ts,
                properties=props,
                person_properties=person_properties or None,
            )
        print(f"  Seeded {sample_size} responses for '{survey.name}'.")
