import json
import uuid
import random
from datetime import timedelta
from typing import Any, Literal, TypedDict
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.models import Survey, Team, User
from posthog.models.event.sql import BULK_INSERT_EVENT_SQL
from posthog.models.person.person import Person, PersonDistinctId


class MultipleChoiceTemplate(TypedDict):
    question: str
    choices: list[str]


class LinkTemplate(TypedDict):
    question: str
    link: str


QuestionType = Literal["open", "rating", "multiple_choice", "link"]
SurveyType = Literal["popover", "widget", "api"]

# Define template types
OpenTemplates = list[str]
RatingTemplates = list[str]
MultipleChoiceTemplates = list[MultipleChoiceTemplate]
LinkTemplates = list[LinkTemplate]


class QuestionTemplates(TypedDict):
    open: OpenTemplates
    rating: RatingTemplates
    multiple_choice: MultipleChoiceTemplates
    link: LinkTemplates


QUESTION_TEMPLATES: QuestionTemplates = {
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

# Sample responses for generating realistic survey response data
# Short responses (1-2 sentences)
OPEN_RESPONSES_SHORT = {
    "feedback": [
        "Love the new dashboard! The analytics are much clearer now.",
        "The interface could be more intuitive. Sometimes I get lost in the navigation.",
        "Great product overall, but loading times could be faster.",
        "Amazing customer support team! They helped me resolve my issue quickly.",
        "The mobile app needs work - it feels clunky compared to the web version.",
        "Pricing is reasonable for the value provided. Very satisfied.",
        "Would love to see more integrations with other tools we use.",
        "The onboarding process was smooth and helpful.",
        "Some features are hard to find. Maybe reorganize the menu?",
        "Excellent reporting capabilities. Saves me hours of work.",
        "The search functionality could be improved.",
        "Love the real-time collaboration features!",
        "Documentation could be more comprehensive.",
        "The API is well-designed and easy to use.",
        "Would appreciate dark mode support.",
    ],
    "improvement": [
        "Better search and filtering options",
        "More customization for dashboards",
        "Faster loading times",
        "Mobile app improvements",
        "More integration options",
        "Better notification system",
        "Improved user interface",
        "More detailed analytics",
        "Better documentation",
        "Enhanced security features",
        "Bulk operations support",
        "Advanced export options",
        "Team collaboration tools",
        "Automation features",
        "Performance optimizations",
    ],
    "experience": [
        "Smooth and intuitive overall",
        "Had some initial learning curve but good now",
        "Very positive, exceeded expectations",
        "Mixed - some great features, some frustrations",
        "Excellent, would recommend to others",
        "Good but room for improvement",
        "Outstanding customer service experience",
        "The setup process was straightforward",
        "Love the clean, modern interface",
        "Sometimes slow but generally reliable",
    ],
    "open_choice": [
        "Custom workflow automation",
        "Integration with Slack",
        "Better mobile experience",
        "Real-time notifications",
        "Advanced filtering options",
        "Custom reporting templates",
        "API access for our use case",
        "Team permissions management",
        "White-label options",
        "Offline mode support",
        "Data export in different formats",
        "Custom branding options",
        "SSO integration",
        "Webhook support",
        "Audit logging",
    ],
}

# Long responses (3-6 sentences) for more detailed feedback
OPEN_RESPONSES_LONG = {
    "feedback": [
        "I've been using your product for about six months now and I have to say it's completely transformed how our team approaches analytics. The dashboard customization options are fantastic and the real-time updates make it easy to stay on top of our key metrics. My only complaint would be that the initial setup took a bit longer than expected, but once everything was configured, it's been smooth sailing. Would definitely recommend to other teams looking for a comprehensive solution.",
        "The product has great potential but there are some serious UX issues that need addressing. First, the navigation is confusing - I often find myself clicking through multiple menus just to find a feature I use daily. Second, the loading times on larger datasets are frustrating and have caused me to lose work when the page times out. Finally, the mobile experience feels like an afterthought. I really want this product to succeed because when it works, it's excellent, but these issues need attention.",
        "We switched from a competitor about three months ago and the difference is night and day. The reporting capabilities are far more advanced and the ability to create custom metrics has been invaluable for our specific use case. Our data team has cut their report generation time by nearly half. The customer success team was also incredibly helpful during our migration - they even hopped on a call to walk us through some of the more complex configurations. Definitely worth the investment.",
        "Overall I'm satisfied with the product but I think there's room for growth in several areas. The core functionality is solid and reliable, which is the most important thing. However, I'd love to see more templates and pre-built configurations for common use cases. Additionally, the learning curve for new team members is steeper than it needs to be - better onboarding materials would help a lot. The pricing is fair for what you get, though the jump between tiers feels a bit steep.",
        "This has become an essential tool for our daily operations. What I appreciate most is how it brings together data from multiple sources into a single unified view - no more switching between different tools and trying to manually correlate information. The API is also well-documented and our developers were able to build custom integrations without much trouble. One area for improvement would be the export functionality - more format options would be helpful for sharing reports with stakeholders who don't have access to the platform.",
        "I want to provide some detailed feedback after using the platform extensively for our Q4 planning. The collaboration features are excellent - being able to share dashboards and insights with specific team members has improved our alignment significantly. The annotation feature is particularly useful for marking important events and explaining data anomalies to stakeholders. However, we've noticed some performance degradation when working with very large date ranges, and the undo functionality is limited. These are minor issues in the grand scheme of things.",
        "As someone who has evaluated dozens of analytics tools over the years, I can confidently say this is one of the better options on the market. The balance between ease of use and powerful features is well-calibrated. New users can get value immediately while power users have access to advanced functionality when needed. The documentation is comprehensive and the community forums are active and helpful. My main suggestion would be to add more video tutorials - some people learn better that way than from written documentation.",
    ],
    "improvement": [
        "The biggest improvement I'd like to see is better bulk editing capabilities. Currently, when I need to update multiple items, I have to do it one by one which is incredibly time-consuming. A multi-select feature with batch actions would save me hours every week. I've seen this in competitor products and it's a game-changer for efficiency. Even just being able to export, edit in a spreadsheet, and re-import would be helpful.",
        "I think the notification system needs a complete overhaul. Right now I get too many notifications for things I don't care about and not enough for things that actually matter. What I'd really like is the ability to set up custom notification rules based on specific conditions and thresholds. For example, I want to be notified immediately when a key metric drops below a certain value, but I only need a daily digest for routine updates. Granular control here would be very valuable.",
        "Please invest more in the mobile app. I frequently need to check on metrics while away from my desk and the current mobile experience is frustrating. The app is slow to load, the charts don't render well on smaller screens, and some features are simply missing. I understand that not everything can be mobile-friendly, but the core viewing and monitoring functionality should work seamlessly. This is becoming a blocker for me when evaluating whether to renew our subscription.",
        "The integration ecosystem needs expansion. We use several tools that don't have native integrations, which means we have to build custom solutions using the API. While the API is good, having native integrations would save us development time and ensure more reliable data syncing. Specifically, I'd love to see integrations with Notion for documentation, Linear for issue tracking, and Figma for design handoffs. These are tools that many teams use together.",
        "I'd like to see more advanced filtering and segmentation options. The current filters are basic and don't allow for complex logical conditions. For instance, I want to filter by users who did action A but not action B within a specific time window - this kind of behavioral segmentation is essential for our analysis but currently requires workarounds or custom queries. Having this built into the UI would make the product much more powerful for our use case.",
    ],
    "experience": [
        "My overall experience has been positive but with some notable friction points along the way. The initial setup was more complex than anticipated - what was promised as a 30-minute setup took our team nearly half a day to complete properly. However, once we got over that hurdle, the day-to-day experience has been smooth. The interface is clean and responsive, and I particularly appreciate the keyboard shortcuts for power users. The recent performance improvements have also been noticeable. We're now processing queries that used to time out without any issues.",
        "I've had a mixed experience that I want to share honestly. The product's strengths are clear - the analytics capabilities are impressive and the visualizations are beautiful. Our executives love the dashboards we've created. However, we've encountered several bugs over the past few months that impacted our workflows. To the team's credit, support has been responsive and most issues were resolved within a day or two. I just wish the QA process caught these issues before they reached production.",
        "Using this product has been a journey of discovery. Every week I seem to find a new feature or capability that I didn't know existed. The depth of functionality is impressive, though it does mean there's a significant learning curve. What's helped is the excellent documentation and the active user community - whenever I'm stuck, I can usually find an answer in the forums or help docs. The team also releases helpful update notes that highlight new features, which is appreciated.",
        "After a year of use, I can say the experience has exceeded our initial expectations. We started with basic analytics needs but have gradually expanded our usage as we discovered more capabilities. The product has scaled well with our growth - we're now processing significantly more data than when we started, and performance has remained consistent. The team has also been receptive to feedback - several features we requested have actually been implemented, which shows they listen to their users.",
        "The experience has been transformative for how our team makes decisions. Before adopting this tool, we relied heavily on intuition and incomplete data. Now we have a single source of truth that everyone can access and understand. The democratization of data across our organization has led to better-informed discussions and more evidence-based strategy. There's still room for improvement in terms of onboarding new team members, but overall I'm very satisfied with what we've been able to accomplish.",
    ],
    "open_choice": [
        "A proper workflow automation system where I can set up triggers and actions. For example, automatically sending a Slack notification when a metric exceeds a threshold, or automatically generating a weekly report and emailing it to stakeholders. Right now I have to either do these things manually or build custom integrations. Native automation would be a huge time-saver and would help ensure important events don't get missed.",
        "Advanced cohort analysis with the ability to track cohorts over time and compare their behaviors. I want to see how users who signed up in January behave differently from those who signed up in March, not just at a point in time but over their entire lifecycle. This longitudinal view is crucial for understanding retention and user development, but currently requires significant manual effort to achieve.",
        "A commenting and discussion feature directly on charts and dashboards. When I share insights with my team, I want to be able to have conversations in context rather than having to jump to Slack or email. Think of it like Google Docs comments but for analytics. This would make collaboration much more efficient and would help preserve the context of discussions for future reference.",
        "Better support for experimentation and A/B testing analysis. I want to be able to easily set up experiments, track results with statistical significance calculations, and get clear recommendations on when tests have reached conclusive results. Currently we have to use a separate tool for experiments and then try to correlate the data, which is cumbersome and error-prone.",
        "A comprehensive audit log that tracks all changes made to dashboards, metrics, and configurations. This is important for compliance reasons but also just for understanding who changed what and when. When something breaks or looks different than expected, I need to be able to trace back the history and understand what happened. This kind of accountability and transparency is essential for any team tool.",
    ],
}

# Backward compatibility: keep OPEN_RESPONSES pointing to short responses
OPEN_RESPONSES = OPEN_RESPONSES_SHORT


class PersonData:
    """Holds person data for event generation."""

    def __init__(self, distinct_id: str, person_uuid: str, properties: dict, created_at: Any):
        self.distinct_id = distinct_id
        self.person_uuid = person_uuid
        self.properties = properties
        self.created_at = created_at


class Command(BaseCommand):
    help = "Generate random surveys for development purposes"

    def get_real_persons(self, team: Team, limit: int = 50) -> list[PersonData]:
        """Fetch real persons from the database that were created by demo data generation."""
        persons_data: list[PersonData] = []

        # Query persons with their distinct IDs
        persons = (
            Person.objects.filter(team_id=team.id)
            .prefetch_related("persondistinctid_set")
            .order_by("-created_at")[:limit]
        )

        for person in persons:
            distinct_ids = PersonDistinctId.objects.filter(person=person, team_id=team.id).values_list(
                "distinct_id", flat=True
            )

            if distinct_ids:
                # Use the first distinct_id for the person
                persons_data.append(
                    PersonData(
                        distinct_id=distinct_ids[0],
                        person_uuid=str(person.uuid),
                        properties=person.properties or {},
                        created_at=person.created_at,
                    )
                )

        return persons_data

    def add_arguments(self, parser):
        parser.add_argument(
            "count",
            type=int,
            nargs="?",
            default=1,
            help="Number of surveys to generate (default: 1)",
        )
        parser.add_argument("--team-id", type=int, help="Team ID to create surveys for")
        parser.add_argument(
            "--responses",
            type=int,
            default=50,
            help="Number of responses to generate per survey (default: 50)",
        )
        parser.add_argument(
            "--days-back",
            type=int,
            default=30,
            help="Generate responses over the last N days (default: 30)",
        )

    def generate_question_of_type(
        self, question_type: QuestionType, choice_type: Literal["single_choice", "multiple_choice"] | None = None
    ) -> dict[str, Any]:
        """Generate a question of a specific type."""
        feature = random.choice(FEATURES)

        if question_type == "open":
            open_templates: list[str] = QUESTION_TEMPLATES["open"]
            open_template = random.choice(open_templates)
            question_text = open_template.format(feature=feature)
            return {
                "type": "open",
                "question": question_text,
                "description": f"Help us improve {feature}",
                "descriptionContentType": "text",
                "optional": random.choice([True, False]),
                "buttonText": random.choice(["Submit", "Next", "Continue"]),
            }

        elif question_type == "rating":
            rating_templates: list[str] = QUESTION_TEMPLATES["rating"]
            rating_template = random.choice(rating_templates)
            question_text = rating_template.format(feature=feature)
            return {
                "type": "rating",
                "question": question_text,
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
            mc_templates: list[MultipleChoiceTemplate] = QUESTION_TEMPLATES["multiple_choice"]
            mc_template = random.choice(mc_templates)
            question_text = mc_template["question"].format(feature=feature)
            actual_type = choice_type if choice_type else random.choice(["single_choice", "multiple_choice"])
            return {
                "type": actual_type,
                "question": question_text,
                "description": f"Select all that apply for {feature}",
                "descriptionContentType": "text",
                "optional": random.choice([True, False]),
                "buttonText": random.choice(["Submit", "Next", "Continue"]),
                "choices": mc_template["choices"],
                "shuffleOptions": random.choice([True, False]),
                "hasOpenChoice": True,  # Always include open-ended option for actionable surveys
            }

        else:  # link
            link_templates: list[LinkTemplate] = QUESTION_TEMPLATES["link"]
            link_template = random.choice(link_templates)
            question_text = link_template["question"].format(feature=feature)
            return {
                "type": "link",
                "question": question_text,
                "description": f"Learn more about {feature}",
                "descriptionContentType": "text",
                "optional": True,
                "buttonText": "Check it out",
                "link": link_template["link"],
            }

    def generate_required_questions(self) -> list[dict[str, Any]]:
        """Generate one question of each actionable type."""
        return [
            self.generate_question_of_type("open"),
            self.generate_question_of_type("rating"),
            self.generate_question_of_type("multiple_choice", choice_type="single_choice"),
            self.generate_question_of_type("multiple_choice", choice_type="multiple_choice"),
        ]

    def generate_random_question(self) -> dict[str, Any]:
        question_type: QuestionType = random.choice(["open", "rating", "multiple_choice", "link"])
        feature = random.choice(FEATURES)

        if question_type == "open":
            # Get a random open question template
            open_templates: list[str] = QUESTION_TEMPLATES["open"]
            open_template = random.choice(open_templates)
            question_text = open_template.format(feature=feature)

            return {
                "type": "open",
                "question": question_text,
                "description": f"Help us improve {feature}",
                "descriptionContentType": "text",
                "optional": random.choice([True, False]),
                "buttonText": random.choice(["Submit", "Next", "Continue"]),
            }

        elif question_type == "rating":
            # Get a random rating question template
            rating_templates: list[str] = QUESTION_TEMPLATES["rating"]
            rating_template = random.choice(rating_templates)
            question_text = rating_template.format(feature=feature)

            return {
                "type": "rating",
                "question": question_text,
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
            # Get a random multiple choice question template
            mc_templates: list[MultipleChoiceTemplate] = QUESTION_TEMPLATES["multiple_choice"]
            mc_template = random.choice(mc_templates)
            question_text = mc_template["question"].format(feature=feature)

            return {
                "type": random.choice(["single_choice", "multiple_choice"]),
                "question": question_text,
                "description": f"Select all that apply for {feature}",
                "descriptionContentType": "text",
                "optional": random.choice([True, False]),
                "buttonText": random.choice(["Submit", "Next", "Continue"]),
                "choices": mc_template["choices"],
                "shuffleOptions": random.choice([True, False]),
                "hasOpenChoice": random.choice([True, False]),
            }

        else:  # link
            # Get a random link question template
            link_templates: list[LinkTemplate] = QUESTION_TEMPLATES["link"]
            link_template = random.choice(link_templates)
            question_text = link_template["question"].format(feature=feature)

            return {
                "type": "link",
                "question": question_text,
                "description": f"Learn more about {feature}",
                "descriptionContentType": "text",
                "optional": True,
                "buttonText": "Check it out",
                "link": link_template["link"],
            }

    def generate_random_survey(self, team_id: int, user_id: int) -> dict[str, Any]:
        # Always include the 4 required actionable question types
        questions = self.generate_required_questions()
        # Shuffle to vary the order
        random.shuffle(questions)

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
            # start_date must be set for survey results to load in the UI
            "start_date": timezone.now() - timedelta(days=60),
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

    def generate_response_for_question(self, question: dict[str, Any]) -> str | list[str] | None:
        """Generate a realistic response for a given question type."""
        question_type = question.get("type")
        question_text = question.get("question", "").lower()

        if question_type == "open":
            # 35% chance of a long response, 65% chance of a short response
            use_long = random.random() < 0.35
            responses = OPEN_RESPONSES_LONG if use_long else OPEN_RESPONSES_SHORT

            if "improve" in question_text or "better" in question_text:
                return random.choice(responses["improvement"])
            elif "experience" in question_text or "feel" in question_text:
                return random.choice(responses["experience"])
            return random.choice(responses["feedback"])

        elif question_type == "rating":
            scale = question.get("scale", 5)
            # Realistic distribution: skewed positive with some variation
            rand = random.random()
            if rand < 0.1:
                return "1"
            elif rand < 0.2:
                return "2"
            elif rand < 0.35:
                return str(min(3, scale))
            elif rand < 0.65:
                return str(min(4, scale))
            return str(scale)

        elif question_type == "single_choice":
            choices = question.get("choices", [])
            has_open_choice = question.get("hasOpenChoice", False)
            if choices:
                # 20% chance of using open-ended response if available
                if has_open_choice and random.random() < 0.2:
                    # 35% chance of a long open choice response
                    responses = OPEN_RESPONSES_LONG if random.random() < 0.35 else OPEN_RESPONSES_SHORT
                    return random.choice(responses["open_choice"])
                # Weight first choice higher (common pattern)
                if random.random() < 0.4:
                    return choices[0]
                return random.choice(choices)
            return None

        elif question_type == "multiple_choice":
            choices = question.get("choices", [])
            has_open_choice = question.get("hasOpenChoice", False)
            if choices:
                # 25% chance of including an open-ended response if available
                if has_open_choice and random.random() < 0.25:
                    num_selections = random.randint(1, min(2, len(choices)))
                    selected = random.sample(choices, num_selections)
                    # 35% chance of a long open choice response
                    responses = OPEN_RESPONSES_LONG if random.random() < 0.35 else OPEN_RESPONSES_SHORT
                    selected.append(random.choice(responses["open_choice"]))
                    return selected
                num_selections = random.randint(1, min(3, len(choices)))
                return random.sample(choices, num_selections)
            return None

        elif question_type == "link":
            # Link questions don't have responses
            return None

        return None

    def _build_event_row(
        self,
        event_name: str,
        properties: dict[str, Any],
        person_data: PersonData,
        timestamp: Any,
        team: Team,
        index: int,
    ) -> tuple[str, dict[str, Any]]:
        """Build a single event row for bulk insertion."""
        # timestamp and created_at are DateTime64(6) - need microseconds
        ts_str = timestamp.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S.%f")
        # person_created_at and group*_created_at are DateTime64 (seconds) - no microseconds
        ts_str_no_micro = timestamp.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        zero_date = "1970-01-01 00:00:00"

        # Format person_created_at from the real person data
        person_created_at_str = zero_date
        if person_data.created_at:
            person_created_at_str = person_data.created_at.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")

        insert = """(
            %(uuid_{i})s,
            %(event_{i})s,
            %(properties_{i})s,
            %(timestamp_{i})s,
            %(team_id_{i})s,
            %(distinct_id_{i})s,
            %(elements_chain_{i})s,
            %(person_id_{i})s,
            %(person_properties_{i})s,
            %(person_created_at_{i})s,
            %(group0_properties_{i})s,
            %(group1_properties_{i})s,
            %(group2_properties_{i})s,
            %(group3_properties_{i})s,
            %(group4_properties_{i})s,
            %(group0_created_at_{i})s,
            %(group1_created_at_{i})s,
            %(group2_created_at_{i})s,
            %(group3_created_at_{i})s,
            %(group4_created_at_{i})s,
            %(person_mode_{i})s,
            %(created_at_{i})s,
            %(_timestamp_{i})s,
            0
        )""".format(i=index)

        params = {
            f"uuid_{index}": str(uuid.uuid4()),
            f"event_{index}": event_name,
            f"properties_{index}": json.dumps(properties),
            f"timestamp_{index}": ts_str,
            f"team_id_{index}": team.id,
            f"distinct_id_{index}": person_data.distinct_id,
            f"elements_chain_{index}": "",
            f"person_id_{index}": person_data.person_uuid,
            f"person_properties_{index}": json.dumps(person_data.properties),
            f"person_created_at_{index}": person_created_at_str,
            f"group0_properties_{index}": "",
            f"group1_properties_{index}": "",
            f"group2_properties_{index}": "",
            f"group3_properties_{index}": "",
            f"group4_properties_{index}": "",
            f"group0_created_at_{index}": zero_date,
            f"group1_created_at_{index}": zero_date,
            f"group2_created_at_{index}": zero_date,
            f"group3_created_at_{index}": zero_date,
            f"group4_created_at_{index}": zero_date,
            f"person_mode_{index}": "full",
            f"created_at_{index}": ts_str,
            f"_timestamp_{index}": ts_str_no_micro,
        }

        return insert, params

    def generate_survey_responses(
        self, survey: Survey, team: Team, num_responses: int, days_back: int, persons_data: list[PersonData]
    ) -> tuple[int, int, int]:
        """Generate survey response events for a survey.

        Inserts directly into ClickHouse for immediate availability.
        Returns tuple of (sent_count, shown_count, dismissed_count).
        """
        if not persons_data:
            self.stdout.write(
                self.style.WARNING(
                    "No persons found in the database. Run 'hogli dev:demo-data' first to generate persons."
                )
            )
            return 0, 0, 0

        now = timezone.now()
        sent_count = 0
        shown_count = 0
        dismissed_count = 0

        # For realism, generate more "shown" events than "sent" (not everyone responds)
        total_shown = int(num_responses * random.uniform(1.3, 1.8))

        inserts: list[str] = []
        params: dict[str, Any] = {}
        event_index = 0

        for i in range(total_shown):
            person_data = random.choice(persons_data)
            # Spread events over the specified time range
            timestamp = now - timedelta(
                days=random.randint(0, days_back),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )

            # Create "survey shown" event
            insert, event_params = self._build_event_row(
                event_name="survey shown",
                properties={
                    "$survey_id": str(survey.id),
                    "$survey_name": survey.name,
                },
                person_data=person_data,
                timestamp=timestamp,
                team=team,
                index=event_index,
            )
            inserts.append(insert)
            params.update(event_params)
            event_index += 1
            shown_count += 1

            # Decide if user responded or dismissed
            if i < num_responses:
                # Generate response
                response_properties: dict[str, Any] = {
                    "$survey_id": str(survey.id),
                    "$survey_name": survey.name,
                }

                # Generate response for each question
                questions = survey.questions or []
                for idx, question in enumerate(questions):
                    response = self.generate_response_for_question(question)
                    if response is not None:
                        if idx == 0:
                            response_properties["$survey_response"] = response
                        else:
                            response_properties[f"$survey_response_{idx}"] = response

                insert, event_params = self._build_event_row(
                    event_name="survey sent",
                    properties=response_properties,
                    person_data=person_data,
                    timestamp=timestamp + timedelta(seconds=random.randint(5, 120)),
                    team=team,
                    index=event_index,
                )
                inserts.append(insert)
                params.update(event_params)
                event_index += 1
                sent_count += 1
            else:
                # Generate dismissed event
                insert, event_params = self._build_event_row(
                    event_name="survey dismissed",
                    properties={
                        "$survey_id": str(survey.id),
                        "$survey_name": survey.name,
                    },
                    person_data=person_data,
                    timestamp=timestamp + timedelta(seconds=random.randint(2, 30)),
                    team=team,
                    index=event_index,
                )
                inserts.append(insert)
                params.update(event_params)
                event_index += 1
                dismissed_count += 1

        # Bulk insert all events directly into ClickHouse
        if inserts:
            sql = BULK_INSERT_EVENT_SQL() + ",".join(inserts)
            sync_execute(sql, params)

        return sent_count, shown_count, dismissed_count

    def handle(self, *args, **options):
        count = options["count"]
        team_id = options["team_id"]
        num_responses = options["responses"]
        days_back = options["days_back"]

        if team_id:
            team = Team.objects.filter(id=team_id).first()
            if not team:
                self.stdout.write(self.style.ERROR(f"Team with ID {team_id} not found."))
                return
        else:
            team = Team.objects.first()
            if not team:
                self.stdout.write(self.style.ERROR("No teams found. Please create a team first."))
                return

        user = User.objects.filter(current_team_id=team.id).first()
        if not user:
            # Fall back to any user in the organization
            user = team.organization.members.first()
        if not user:
            self.stdout.write(self.style.ERROR(f"No users found for team {team.id}"))
            return

        total_sent = 0
        total_shown = 0
        total_dismissed = 0

        # Fetch real persons from the database if responses are requested
        persons_data: list[PersonData] = []
        if num_responses > 0:
            persons_data = self.get_real_persons(team, limit=100)
            if persons_data:
                self.stdout.write(
                    self.style.SUCCESS(f"Found {len(persons_data)} persons in the database to use for responses")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "No persons found in the database. Run 'hogli dev:demo-data' first to generate persons."
                    )
                )

        for _ in range(count):
            survey_data = self.generate_random_survey(team.id, user.id)
            survey = Survey.objects.create(**survey_data)

            # Backdate created_at so that generated events (spread over days_back days) fall within
            # the survey's timestamp filter (which uses created_at as the start date)
            if num_responses > 0:
                backdated_created_at = timezone.now() - timedelta(days=days_back + 1)
                Survey.objects.filter(id=survey.id).update(created_at=backdated_created_at)
                survey.refresh_from_db()

            self.stdout.write(self.style.SUCCESS(f'Created survey "{survey.name}" (ID: {survey.id})'))

            if num_responses > 0 and persons_data:
                sent, shown, dismissed = self.generate_survey_responses(
                    survey, team, num_responses, days_back, persons_data
                )
                total_sent += sent
                total_shown += shown
                total_dismissed += dismissed
                self.stdout.write(f"  Generated {sent} responses, {shown} shown events, {dismissed} dismissed events")

        if num_responses > 0:
            self.stdout.write(
                self.style.SUCCESS(f"\nTotal: {total_sent} responses, {total_shown} shown, {total_dismissed} dismissed")
            )
