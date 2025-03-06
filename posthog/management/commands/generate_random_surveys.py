import random
from typing import Any, TypedDict, Literal, Union
from django.core.management.base import BaseCommand
from posthog.models import Team, Survey, User


class MultipleChoiceTemplate(TypedDict):
    question: str
    choices: list[str]


class LinkTemplate(TypedDict):
    question: str
    link: str


QuestionType = Literal["open", "rating", "multiple_choice", "link"]
SurveyType = Literal["popover", "widget", "api"]

QUESTION_TEMPLATES: dict[str, Union[list[str], list[MultipleChoiceTemplate], list[LinkTemplate]]] = {
    "open": [
        "What do you think of our {feature}?",
        "How can we improve {feature}?",
        "What's your favorite thing about {feature}?",
        "What's missing from {feature}?",
        "What would make {feature} better for you?",
    ],
    "rating": [
        "How would you rate {feature}?",
        "How satisfied are you with {feature}?",
        "How likely are you to recommend {feature}?",
        "How easy was it to use {feature}?",
        "How valuable is {feature} to you?",
    ],
    "multiple_choice": [
        {
            "question": "Which aspects of {feature} do you use most?",
            "choices": ["Feature A", "Feature B", "Feature C", "Feature D", "Other"],
        },
        {
            "question": "How often do you use {feature}?",
            "choices": ["Daily", "Weekly", "Monthly", "Rarely", "Never"],
        },
    ],
    "link": [
        {
            "question": "Would you like to learn more about {feature}?",
            "link": "https://posthog.com/docs/feature",
        },
        {
            "question": "Check out our guide on {feature}",
            "link": "https://posthog.com/tutorials/feature",
        },
    ],
}

FEATURES = [
    "dashboards",
    "insights",
    "feature flags",
    "experiments",
    "session recordings",
    "surveys",
    "notebooks",
    "data warehouse",
    "cohorts",
    "annotations",
]


class Command(BaseCommand):
    help = "Generate random surveys for development purposes"

    def add_arguments(self, parser):
        parser.add_argument("count", type=int, help="Number of surveys to generate")
        parser.add_argument("--team-id", type=int, help="Team ID to create surveys for")

    def generate_random_question(self) -> dict[str, Any]:
        question_type: QuestionType = random.choice(["open", "rating", "multiple_choice", "link"])
        feature = random.choice(FEATURES)

        if question_type == "open":
            template: str = random.choice(QUESTION_TEMPLATES["open"])  # type: ignore
            return {
                "type": "open",
                "question": template.format(feature=feature),
                "description": f"Help us improve {feature}",
                "descriptionContentType": "text",
                "optional": random.choice([True, False]),
                "buttonText": random.choice(["Submit", "Next", "Continue"]),
            }
        elif question_type == "rating":
            template: str = random.choice(QUESTION_TEMPLATES["rating"])  # type: ignore
            return {
                "type": "rating",
                "question": template.format(feature=feature),
                "description": f"Rate your experience with {feature}",
                "descriptionContentType": "text",
                "optional": random.choice([True, False]),
                "buttonText": random.choice(["Submit", "Next", "Continue"]),
                "display": random.choice(["number", "emoji"]),
                "scale": random.choice([5, 7, 10]),
                "lowerBoundLabel": "Not at all",
                "upperBoundLabel": "Extremely",
            }
        elif question_type == "multiple_choice":
            template: MultipleChoiceTemplate = random.choice(QUESTION_TEMPLATES["multiple_choice"])  # type: ignore
            return {
                "type": random.choice(["single_choice", "multiple_choice"]),
                "question": template["question"].format(feature=feature),
                "description": f"Select all that apply for {feature}",
                "descriptionContentType": "text",
                "optional": random.choice([True, False]),
                "buttonText": random.choice(["Submit", "Next", "Continue"]),
                "choices": template["choices"],
                "shuffleOptions": random.choice([True, False]),
                "hasOpenChoice": random.choice([True, False]),
            }
        else:  # link
            template: LinkTemplate = random.choice(QUESTION_TEMPLATES["link"])  # type: ignore
            return {
                "type": "link",
                "question": template["question"].format(feature=feature),
                "description": f"Learn more about {feature}",
                "descriptionContentType": "text",
                "optional": True,
                "buttonText": "Check it out",
                "link": template["link"],
            }

    def generate_random_survey(self, team_id: int, user_id: int) -> dict[str, Any]:
        num_questions = random.randint(1, 5)
        questions = [self.generate_random_question() for _ in range(num_questions)]

        # Generate a name based on the questions
        question_types = [q["type"] for q in questions]
        feature_mentions = [f for f in FEATURES if any(f in q.get("question", "") for q in questions)]
        survey_type: SurveyType = random.choice(["popover", "widget", "api"])
        name = f"[{survey_type.upper()}] {' & '.join(set(question_types))} survey about {' & '.join(feature_mentions)}"

        return {
            "team_id": team_id,
            "name": name,
            "description": f"Gathering feedback about {' and '.join(feature_mentions)}",
            "type": survey_type,
            "questions": questions,
            "appearance": {
                "thankYouMessageHeader": "Thanks for your feedback!",
                "thankYouMessageDescription": "We'll use it to improve our product.",
                "thankYouMessageDescriptionContentType": "text",
                "surveyPopupDelaySeconds": random.randint(0, 60),
                "fontFamily": "system-ui",
                "backgroundColor": "#eeeded",
                "submitButtonColor": "black",
                "submitButtonTextColor": "white",
                "ratingButtonColor": "white",
                "ratingButtonActiveColor": "black",
                "borderColor": "#c9c6c6",
                "placeholder": "Start typing...",
                "whiteLabel": False,
                "displayThankYouMessage": True,
                "position": "right",
                "widgetType": "tab",
                "widgetLabel": "Feedback",
                "widgetColor": "black",
            },
            "created_by_id": user_id,
            "archived": False,
            # Additional default fields from NEW_SURVEY
            "schedule": "once",
            "linked_flag_id": None,
            "linked_flag": None,
            "targeting_flag": None,
            "start_date": None,
            "end_date": None,
            "conditions": None,
            "responses_limit": None,
            "iteration_count": None,
            "iteration_frequency_days": None,
            "internal_targeting_flag": None,
            "internal_response_sampling_flag": None,
            "response_sampling_start_date": None,
            "response_sampling_interval_type": None,
            "response_sampling_interval": None,
            "response_sampling_limit": None,
            "response_sampling_daily_limits": None,
        }

    def handle(self, *args, **options):
        count = options["count"]
        team_id = options["team_id"]

        if not team_id:
            team = Team.objects.first()
            if not team:
                self.stdout.write(self.style.ERROR("No teams found. Please create a team first."))
                return
            team_id = team.id

        user = User.objects.filter(current_team_id=team_id).first()
        if not user:
            self.stdout.write(self.style.ERROR(f"No users found for team {team_id}"))
            return

        for _ in range(count):
            survey_data = self.generate_random_survey(team_id, user.id)
            survey = Survey.objects.create(**survey_data)
            self.stdout.write(self.style.SUCCESS(f'Created survey "{survey.name}" (ID: {survey.id})'))
