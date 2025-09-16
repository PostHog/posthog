import uuid
import datetime

import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase, Score

from posthog.models import Survey

from products.surveys.backend.max_tools import SurveyAnalysisTool

from ..base import MaxPublicEval


# Helper functions to generate test response data
def generate_test_data_responses():
    """Generate clearly placeholder/test responses that should be detected as test data."""
    return [
        {
            "questionName": "What do you think about our product?",
            "questionId": "q1",
            "responses": [
                {
                    "responseText": "fasdfasdf",
                    "userDistinctId": "user1",
                    "email": "test@example.com",
                    "isOpenEnded": True,
                },
                {"responseText": "abc", "userDistinctId": "user2", "email": None, "isOpenEnded": True},
                {"responseText": "hello", "userDistinctId": "user3", "email": None, "isOpenEnded": True},
                {"responseText": "asdfasdf", "userDistinctId": "user4", "email": None, "isOpenEnded": True},
                {"responseText": "test123", "userDistinctId": "user5", "email": None, "isOpenEnded": True},
                {"responseText": "qwerty", "userDistinctId": "user6", "email": None, "isOpenEnded": True},
                {
                    "responseText": "testing",
                    "userDistinctId": "user7",
                    "email": "test2@example.com",
                    "isOpenEnded": True,
                },
                {"responseText": "abcdef", "userDistinctId": "user8", "email": None, "isOpenEnded": True},
                {"responseText": "123456", "userDistinctId": "user9", "email": None, "isOpenEnded": True},
                {"responseText": "hjkl", "userDistinctId": "user10", "email": None, "isOpenEnded": True},
                {"responseText": "aaaa", "userDistinctId": "user11", "email": None, "isOpenEnded": True},
                {"responseText": "test", "userDistinctId": "user12", "email": "test3@example.com", "isOpenEnded": True},
                {"responseText": "fdsa", "userDistinctId": "user13", "email": None, "isOpenEnded": True},
                {"responseText": "random", "userDistinctId": "user14", "email": None, "isOpenEnded": True},
                {"responseText": "keyboard", "userDistinctId": "user15", "email": None, "isOpenEnded": True},
                {"responseText": "asdf", "userDistinctId": "user16", "email": None, "isOpenEnded": True},
                {"responseText": "xyz", "userDistinctId": "user17", "email": None, "isOpenEnded": True},
                {"responseText": "placeholder", "userDistinctId": "user18", "email": None, "isOpenEnded": True},
                {"responseText": "sample", "userDistinctId": "user19", "email": None, "isOpenEnded": True},
                {"responseText": "lorem ipsum", "userDistinctId": "user20", "email": None, "isOpenEnded": True},
            ],
        }
    ]


def generate_mixed_data_responses():
    """Generate mixed test and genuine responses (60% test, 40% genuine)."""
    test_responses = [
        {"responseText": "fasdfasdf", "userDistinctId": "user1", "email": "test@example.com", "isOpenEnded": True},
        {"responseText": "abc", "userDistinctId": "user2", "email": None, "isOpenEnded": True},
        {"responseText": "testing123", "userDistinctId": "user3", "email": None, "isOpenEnded": True},
        {"responseText": "hello world", "userDistinctId": "user4", "email": "test2@example.com", "isOpenEnded": True},
        {"responseText": "qwerty", "userDistinctId": "user5", "email": None, "isOpenEnded": True},
        {"responseText": "asdf", "userDistinctId": "user6", "email": None, "isOpenEnded": True},
        {"responseText": "sample text", "userDistinctId": "user7", "email": None, "isOpenEnded": True},
        {"responseText": "test response", "userDistinctId": "user8", "email": None, "isOpenEnded": True},
        {"responseText": "placeholder", "userDistinctId": "user9", "email": None, "isOpenEnded": True},
        {"responseText": "random", "userDistinctId": "user10", "email": None, "isOpenEnded": True},
        {"responseText": "filler", "userDistinctId": "user11", "email": None, "isOpenEnded": True},
        {"responseText": "nothing", "userDistinctId": "user12", "email": None, "isOpenEnded": True},
        {"responseText": "blah", "userDistinctId": "user13", "email": None, "isOpenEnded": True},
        {"responseText": "xyz123", "userDistinctId": "user14", "email": None, "isOpenEnded": True},
        {"responseText": "keyboard mash", "userDistinctId": "user15", "email": None, "isOpenEnded": True},
    ]

    genuine_responses = [
        # Interface feedback
        {
            "responseText": "The main dashboard is cluttered and hard to navigate quickly",
            "userDistinctId": "user16",
            "email": "real1@user.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Interface could be more intuitive, buttons are not where I expect",
            "userDistinctId": "user17",
            "email": "real2@user.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Navigation menu needs work - took me 5 minutes to find settings",
            "userDistinctId": "user18",
            "email": "real3@user.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Love the clean design but some UI elements are too small on mobile",
            "userDistinctId": "user19",
            "email": "real4@user.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Search functionality in the interface is hard to find and use",
            "userDistinctId": "user20",
            "email": "real5@user.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "The sidebar gets in the way on smaller screens",
            "userDistinctId": "user21",
            "email": "real6@user.com",
            "isOpenEnded": True,
        },
        # Performance feedback
        {
            "responseText": "Loading times are really slow, especially for large datasets",
            "userDistinctId": "user22",
            "email": "real7@user.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "App crashes when I upload files bigger than 50MB",
            "userDistinctId": "user23",
            "email": "real8@user.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Performance on mobile is terrible, very laggy scrolling",
            "userDistinctId": "user24",
            "email": "real9@user.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Would love faster sync between devices, currently takes forever",
            "userDistinctId": "user25",
            "email": "real10@user.com",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "How can we improve our product?",
            "questionId": "q1",
            "responses": test_responses + genuine_responses,
        }
    ]


def generate_positive_feedback_responses():
    """Generate genuine positive feedback across multiple themes."""
    ui_design_responses = [
        {
            "responseText": "The user interface is incredibly clean and intuitive to navigate",
            "userDistinctId": "user1",
            "email": "user1@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Love the modern design - feels professional and polished",
            "userDistinctId": "user2",
            "email": "user2@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Dashboard layout makes it easy to find everything I need quickly",
            "userDistinctId": "user3",
            "email": "user3@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "The visual hierarchy is perfect - important things stand out",
            "userDistinctId": "user4",
            "email": "user4@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Responsive design works beautifully on all my devices",
            "userDistinctId": "user5",
            "email": "user5@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Color scheme and typography are excellent choices",
            "userDistinctId": "user6",
            "email": "user6@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Interface feels modern and doesn't look outdated like competitors",
            "userDistinctId": "user7",
            "email": "user7@company.com",
            "isOpenEnded": True,
        },
    ]

    performance_responses = [
        {
            "responseText": "Lightning fast loading times even with large datasets",
            "userDistinctId": "user8",
            "email": "user8@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Never experienced crashes or bugs - very stable platform",
            "userDistinctId": "user9",
            "email": "user9@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Real-time updates happen instantly without any lag",
            "userDistinctId": "user10",
            "email": "user10@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Performance is consistently excellent across all features",
            "userDistinctId": "user11",
            "email": "user11@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Handles our heavy usage without any slowdowns",
            "userDistinctId": "user12",
            "email": "user12@company.com",
            "isOpenEnded": True,
        },
    ]

    support_responses = [
        {
            "responseText": "Customer support team is incredibly knowledgeable and responsive",
            "userDistinctId": "user13",
            "email": "user13@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Got help within 15 minutes via chat - amazing service",
            "userDistinctId": "user14",
            "email": "user14@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Support goes above and beyond to solve problems",
            "userDistinctId": "user15",
            "email": "user15@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Documentation is thorough and support articles are really helpful",
            "userDistinctId": "user16",
            "email": "user16@company.com",
            "isOpenEnded": True,
        },
    ]

    integration_responses = [
        {
            "responseText": "Seamless integration with all our existing tools and workflows",
            "userDistinctId": "user17",
            "email": "user17@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "API is well-documented and easy to implement",
            "userDistinctId": "user18",
            "email": "user18@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Fits perfectly into our daily workflow without disruption",
            "userDistinctId": "user19",
            "email": "user19@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Export functionality works exactly as expected with our systems",
            "userDistinctId": "user20",
            "email": "user20@company.com",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "What do you like most about our product?",
            "questionId": "q1",
            "responses": ui_design_responses + performance_responses + support_responses + integration_responses,
        }
    ]


def generate_negative_feedback_responses():
    """Generate genuine negative feedback across problem areas."""
    performance_issues = [
        {
            "responseText": "App crashes constantly when I try to upload files larger than 100MB",
            "userDistinctId": "user1",
            "email": "user1@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Loading times are painfully slow - sometimes 30+ seconds for simple queries",
            "userDistinctId": "user2",
            "email": "user2@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "System goes down for maintenance way too often, always during business hours",
            "userDistinctId": "user3",
            "email": "user3@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Data syncing is unreliable - lost work multiple times due to sync failures",
            "userDistinctId": "user4",
            "email": "user4@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Memory usage is insane - laptop becomes unusable when running your app",
            "userDistinctId": "user5",
            "email": "user5@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Frequent timeouts when working with larger datasets, very frustrating",
            "userDistinctId": "user6",
            "email": "user6@company.com",
            "isOpenEnded": True,
        },
    ]

    support_problems = [
        {
            "responseText": "Support tickets take 3-5 days to get any response, completely unacceptable",
            "userDistinctId": "user7",
            "email": "user7@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "When support finally responds, they ask basic questions I already answered",
            "userDistinctId": "user8",
            "email": "user8@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "No phone support option - only slow email tickets for urgent issues",
            "userDistinctId": "user9",
            "email": "user9@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Support team clearly doesn't understand their own product features",
            "userDistinctId": "user10",
            "email": "user10@company.com",
            "isOpenEnded": True,
        },
    ]

    pricing_concerns = [
        {
            "responseText": "Way overpriced compared to competitors offering similar features",
            "userDistinctId": "user11",
            "email": "user11@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Hidden fees keep appearing - billing is not transparent at all",
            "userDistinctId": "user12",
            "email": "user12@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Free tier is basically useless - forces you to upgrade immediately",
            "userDistinctId": "user13",
            "email": "user13@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Poor value for money - paying premium prices for basic functionality",
            "userDistinctId": "user14",
            "email": "user14@company.com",
            "isOpenEnded": True,
        },
    ]

    missing_features = [
        {
            "responseText": "No bulk operations - have to do everything one by one, super tedious",
            "userDistinctId": "user15",
            "email": "user15@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Missing basic export options that every competitor has",
            "userDistinctId": "user16",
            "email": "user16@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "No offline mode - completely useless when internet is spotty",
            "userDistinctId": "user17",
            "email": "user17@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Collaboration features are primitive compared to modern standards",
            "userDistinctId": "user18",
            "email": "user18@company.com",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "What issues or problems have you encountered with our product?",
            "questionId": "q1",
            "responses": performance_issues + support_problems + pricing_concerns + missing_features,
        }
    ]


def generate_multi_question_responses():
    """Generate responses for multiple questions with varied feedback types."""
    positive_responses = [
        # Ease of use feedback
        {
            "responseText": "Incredibly intuitive interface - figured it out in minutes",
            "userDistinctId": "user1",
            "email": "user1@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Simple workflow that doesn't require extensive training",
            "userDistinctId": "user2",
            "email": "user2@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Clean design makes complex tasks feel manageable",
            "userDistinctId": "user3",
            "email": "user3@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Onboarding process was smooth and well-guided",
            "userDistinctId": "user4",
            "email": "user4@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Everything is where you'd expect it to be",
            "userDistinctId": "user5",
            "email": "user5@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "No steep learning curve unlike other similar tools",
            "userDistinctId": "user6",
            "email": "user6@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "User experience feels thoughtfully designed",
            "userDistinctId": "user7",
            "email": "user7@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Great balance of powerful features without complexity",
            "userDistinctId": "user8",
            "email": "user8@company.com",
            "isOpenEnded": True,
        },
        # Reliability feedback
        {
            "responseText": "Rock solid performance - never had any crashes or issues",
            "userDistinctId": "user9",
            "email": "user9@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Data integrity is excellent, never lost any work",
            "userDistinctId": "user10",
            "email": "user10@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Consistent uptime - can always rely on it being available",
            "userDistinctId": "user11",
            "email": "user11@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Fast loading and response times across all features",
            "userDistinctId": "user12",
            "email": "user12@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Auto-save functionality has saved me multiple times",
            "userDistinctId": "user13",
            "email": "user13@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Handles large amounts of data without slowing down",
            "userDistinctId": "user14",
            "email": "user14@company.com",
            "isOpenEnded": True,
        },
    ]

    improvement_responses = [
        # Advanced features
        {
            "responseText": "Need bulk operations for managing hundreds of items at once",
            "userDistinctId": "user1",
            "email": "user1@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Advanced filtering and search capabilities would be game-changing",
            "userDistinctId": "user2",
            "email": "user2@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "API access for custom integrations with our internal tools",
            "userDistinctId": "user3",
            "email": "user3@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Custom dashboards and reporting features for management",
            "userDistinctId": "user4",
            "email": "user4@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Automation rules and workflows to reduce manual work",
            "userDistinctId": "user5",
            "email": "user5@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "More granular permission controls for team management",
            "userDistinctId": "user6",
            "email": "user6@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Advanced analytics and insights into usage patterns",
            "userDistinctId": "user7",
            "email": "user7@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Better collaboration tools for larger teams",
            "userDistinctId": "user8",
            "email": "user8@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "White-label options for client-facing implementations",
            "userDistinctId": "user9",
            "email": "user9@company.com",
            "isOpenEnded": True,
        },
        # Mobile improvements
        {
            "responseText": "Mobile app needs significant performance improvements",
            "userDistinctId": "user10",
            "email": "user10@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Offline mode for working without internet connection",
            "userDistinctId": "user11",
            "email": "user11@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Native mobile apps instead of web-based mobile experience",
            "userDistinctId": "user12",
            "email": "user12@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Better mobile interface optimization for small screens",
            "userDistinctId": "user13",
            "email": "user13@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Faster loading times on mobile devices",
            "userDistinctId": "user14",
            "email": "user14@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Push notifications for mobile app would be useful",
            "userDistinctId": "user15",
            "email": "user15@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Dark mode theme option for better user experience",
            "userDistinctId": "user16",
            "email": "user16@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Keyboard shortcuts for power users on desktop",
            "userDistinctId": "user17",
            "email": "user17@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Better browser compatibility, especially for older versions",
            "userDistinctId": "user18",
            "email": "user18@company.com",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "What do you like about our product?",
            "questionId": "q1",
            "responses": positive_responses,
        },
        {
            "questionName": "What could we improve or add?",
            "questionId": "q2",
            "responses": improvement_responses,
        },
    ]


def generate_service_feedback_responses():
    """Generate customer service feedback with varied quality levels."""
    excellent_service = [
        {
            "responseText": "Customer support resolved my issue within 2 hours - absolutely fantastic",
            "userDistinctId": "user1",
            "email": "customer1@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Representative was knowledgeable and patient, walked me through everything step by step",
            "userDistinctId": "user2",
            "email": "customer2@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "24/7 chat support is a game changer for our international team",
            "userDistinctId": "user3",
            "email": "customer3@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Proactive communication about updates and maintenance - really appreciate that",
            "userDistinctId": "user4",
            "email": "customer4@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Technical support team understood our complex setup immediately",
            "userDistinctId": "user5",
            "email": "customer5@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Follow-up email to ensure problem was fully resolved shows they care",
            "userDistinctId": "user6",
            "email": "customer6@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Support documentation is comprehensive and easy to follow",
            "userDistinctId": "user7",
            "email": "customer7@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Video tutorials provided by support team were extremely helpful",
            "userDistinctId": "user8",
            "email": "customer8@business.com",
            "isOpenEnded": True,
        },
    ]

    moderate_service = [
        {
            "responseText": "Good service overall but had to wait 30 minutes for initial response",
            "userDistinctId": "user9",
            "email": "customer9@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Support was helpful but had to explain the issue multiple times",
            "userDistinctId": "user10",
            "email": "customer10@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Eventually got the answer I needed, took a few back-and-forth messages",
            "userDistinctId": "user11",
            "email": "customer11@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Phone support was good but email responses are quite slow",
            "userDistinctId": "user12",
            "email": "customer12@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Representative was polite but didn't seem familiar with advanced features",
            "userDistinctId": "user13",
            "email": "customer13@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Got my problem solved but the process felt longer than necessary",
            "userDistinctId": "user14",
            "email": "customer14@business.com",
            "isOpenEnded": True,
        },
    ]

    poor_service = [
        {
            "responseText": "Waited over 2 hours for someone to respond to urgent issue",
            "userDistinctId": "user15",
            "email": "customer15@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "First agent couldn't help, was transferred 3 times before getting answer",
            "userDistinctId": "user16",
            "email": "customer16@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Support ticket was closed without resolution, had to reopen",
            "userDistinctId": "user17",
            "email": "customer17@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Generic responses that didn't address my specific technical problem",
            "userDistinctId": "user18",
            "email": "customer18@business.com",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "How would you rate our customer service experience?",
            "questionId": "q1",
            "responses": excellent_service + moderate_service + poor_service,
        }
    ]


def generate_feature_request_responses():
    """Generate detailed feature requests across different categories."""
    integration_requests = [
        {
            "responseText": "Integration with Slack would revolutionize our team communication workflow",
            "userDistinctId": "user1",
            "email": "dev1@startup.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Google Workspace SSO integration is desperately needed for enterprise deployment",
            "userDistinctId": "user2",
            "email": "admin@corp.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Zapier integration would allow us to automate so many manual processes",
            "userDistinctId": "user3",
            "email": "ops@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Microsoft Teams integration for seamless file sharing and notifications",
            "userDistinctId": "user4",
            "email": "user4@enterprise.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "API endpoints for custom reporting would enable our dashboard integrations",
            "userDistinctId": "user5",
            "email": "engineer@tech.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Salesforce CRM integration to sync customer data automatically",
            "userDistinctId": "user6",
            "email": "sales@company.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Webhook support for real-time data synchronization with our systems",
            "userDistinctId": "user7",
            "email": "dev7@startup.com",
            "isOpenEnded": True,
        },
    ]

    mobile_improvements = [
        {
            "responseText": "Offline mode for mobile app would be incredible for field work",
            "userDistinctId": "user8",
            "email": "field@service.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Push notifications for important updates and deadlines",
            "userDistinctId": "user9",
            "email": "manager@team.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Mobile photo upload with automatic compression and organization",
            "userDistinctId": "user10",
            "email": "photographer@agency.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Better tablet interface optimized for larger screens",
            "userDistinctId": "user11",
            "email": "designer@studio.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Voice-to-text input for quick note taking on mobile",
            "userDistinctId": "user12",
            "email": "consultant@firm.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Dark mode theme for mobile app to reduce eye strain",
            "userDistinctId": "user13",
            "email": "user13@company.com",
            "isOpenEnded": True,
        },
    ]

    analytics_reporting = [
        {
            "responseText": "Advanced analytics dashboard with customizable KPI tracking",
            "userDistinctId": "user14",
            "email": "analyst@metrics.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Automated report scheduling and email delivery to stakeholders",
            "userDistinctId": "user15",
            "email": "director@corp.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Data export in more formats like Excel, PDF, and CSV",
            "userDistinctId": "user16",
            "email": "accountant@business.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Real-time collaboration analytics to track team productivity",
            "userDistinctId": "user17",
            "email": "pm@startup.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Historical trend analysis with predictive insights",
            "userDistinctId": "user18",
            "email": "strategist@consulting.com",
            "isOpenEnded": True,
        },
    ]

    ux_improvements = [
        {
            "responseText": "Keyboard shortcuts for power users would dramatically improve efficiency",
            "userDistinctId": "user19",
            "email": "poweruser@tech.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Multi-language support for our international team members",
            "userDistinctId": "user20",
            "email": "global@multinational.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Bulk operations for managing large datasets more efficiently",
            "userDistinctId": "user21",
            "email": "datamanager@enterprise.com",
            "isOpenEnded": True,
        },
        {
            "responseText": "Template system for recurring workflows and standardized processes",
            "userDistinctId": "user22",
            "email": "operations@company.com",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "What features would you like to see added or improved?",
            "questionId": "q1",
            "responses": integration_requests + mobile_improvements + analytics_reporting + ux_improvements,
        }
    ]


@pytest.fixture
async def create_test_surveys(demo_org_team_user):
    """Create test surveys for evaluation."""
    _, team, user = demo_org_team_user

    test_surveys = []
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    survey_names = [
        f"Test Survey with Placeholder Data {timestamp}",
        f"Mixed Data Survey {timestamp}",
        f"Customer Satisfaction Survey {timestamp}",
        f"Product Issues Survey {timestamp}",
        f"Comprehensive Feedback Survey {timestamp}",
        f"Support Service Survey {timestamp}",
        f"Feature Requests Survey {timestamp}",
    ]

    for name in survey_names:
        survey = await Survey.objects.acreate(
            team=team,
            created_by=user,
            name=name,
            description=f"Test survey: {name}",
            questions=[
                {"type": "open", "question": "What do you think?", "id": str(uuid.uuid4())},
                {"type": "open", "question": "Any other feedback?", "id": str(uuid.uuid4())},
            ],
            type="popover",
        )
        test_surveys.append(survey)

    return test_surveys


@pytest.fixture
async def call_survey_analysis_tool(demo_org_team_user, create_test_surveys):
    """
    This fixture creates a properly configured SurveyAnalysisTool for evaluation.
    """
    _, team, user = demo_org_team_user
    test_surveys = create_test_surveys

    async def call_analysis_tool(context: dict) -> dict:
        """
        Call the survey analysis tool with provided context and return structured output.
        """
        try:
            # Get the right survey ID for the test case
            survey_index = context.get("survey_index", 0)
            if survey_index < len(test_surveys):
                survey = test_surveys[survey_index]
                # Update context with real survey data
                context = {
                    **context,
                    "survey_id": str(survey.id),
                    "survey_name": survey.name,
                }

            # Create the analysis tool
            analysis_tool = SurveyAnalysisTool(team=team, user=user)

            # Set the context (this simulates what the frontend would pass)
            analysis_tool._context = context

            # Call the tool
            result = await analysis_tool._arun_impl()

            # Return structured output
            user_message, artifact = result
            return {
                "success": True,
                "user_message": user_message,
                "artifact": artifact,
            }

        except Exception as e:
            return {
                "success": False,
                "user_message": f"❌ Analysis failed: {str(e)}",
                "artifact": None,
                "error": str(e),
            }

    return call_analysis_tool


class TestDataDetectionScorer(LLMClassifier):
    """
    Evaluate if the tool correctly identifies test/placeholder data vs genuine feedback.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="test_data_detection",
            prompt_template="""
Evaluate whether the survey analysis tool correctly identified if the responses are test/placeholder data or genuine user feedback.

Survey Context:
Survey ID: {{input.survey_id}}
Survey Name: {{input.survey_name}}
Response Data: {{input.formatted_responses}}

Analysis Output:
User Message: {{output.user_message}}
Success: {{output.success}}

Expected Classification: {{expected.data_type}}

Evaluation Criteria:
1. **Correct Classification**: Did the tool correctly identify whether responses are test data or genuine feedback?
2. **Test Data Patterns**: For test data, did it identify patterns like "fasdfasdf", "abc", random keystrokes?
3. **Genuine Data Recognition**: For genuine feedback, did it avoid false positive test data detection?
4. **Appropriate Response**: Did the tool provide appropriate analysis or recommendations based on data quality?
5. **No Hallucination**: Did it avoid creating fictional themes from meaningless test responses?

Test data indicators: Random keystrokes, repeated "abc", "hello", "asdf", "fasdfasdf", etc.
Genuine data indicators: Coherent sentences, actual feedback, meaningful responses.

How accurately did the tool detect the data type? Choose one:
- perfect: Correctly identified data type and provided appropriate response
- good: Mostly correct identification with minor issues
- partial: Some correct aspects but missed key data quality indicators
- incorrect: Completely misclassified the data type or hallucinated analysis
""".strip(),
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "incorrect": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )
        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )
        return super()._run_eval_sync(output, expected, **kwargs)


class ThemeExtractionQualityScorer(LLMClassifier):
    """
    Evaluate the quality of theme extraction from genuine user feedback.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="theme_extraction_quality",
            prompt_template="""
Evaluate the quality of themes extracted from survey responses.

Survey Responses: {{input.formatted_responses}}

Extracted Themes: {{output.artifact.analysis.themes}}
Analysis Insights: {{output.artifact.analysis.insights}}

Expected Themes: {{expected.expected_themes}}

Evaluation Criteria:
1. **Relevance**: Are the extracted themes actually present in the responses?
2. **Completeness**: Did the analysis capture the main themes from the responses?
3. **Accuracy**: Are the themes accurately representing what users said?
4. **Specificity**: Are themes specific enough to be actionable, not too generic?
5. **No Hallucination**: Are all themes based on actual response content?

Note: Themes don't need to match expected themes exactly, but should be legitimate interpretations of the response data.

How would you rate the theme extraction quality? Choose one:
- excellent: Themes are accurate, complete, and actionable based on actual responses
- good: Themes are mostly accurate with minor issues or omissions
- adequate: Some good themes but missing key patterns or slightly generic
- poor: Inaccurate themes, significant hallucination, or missed major patterns
""".strip(),
            choice_scores={
                "excellent": 1.0,
                "good": 0.75,
                "adequate": 0.5,
                "poor": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        # Only evaluate if we have genuine data and successful analysis
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )

        # Skip for test data scenarios
        if expected and expected.get("data_type") == "test":
            return None

        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )

        # Skip for test data scenarios
        if expected and expected.get("data_type") == "test":
            return None

        return super()._run_eval_sync(output, expected, **kwargs)


class RecommendationQualityScorer(LLMClassifier):
    """
    Evaluate the quality and actionability of recommendations.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="recommendation_quality",
            prompt_template="""
Evaluate the quality of recommendations generated from survey analysis.

Survey Responses: {{input.formatted_responses}}
Generated Recommendations: {{output.artifact.analysis.recommendations}}

Evaluation Criteria:
1. **Actionability**: Are recommendations specific and actionable, not generic advice?
2. **Relevance**: Are recommendations directly based on the survey insights?
3. **Feasibility**: Are recommendations realistic for a product team to implement?
4. **Prioritization**: Are the most important recommendations prioritized appropriately?
5. **Clarity**: Are recommendations clear and well-articulated?

For test data scenarios: Recommendations should acknowledge data quality issues and suggest collecting genuine feedback.

How would you rate the recommendation quality? Choose one:
- excellent: Recommendations are highly actionable, relevant, and well-prioritized
- good: Recommendations are mostly actionable with minor issues
- adequate: Some good recommendations but could be more specific or better prioritized
- poor: Generic, irrelevant, or non-actionable recommendations
""".strip(),
            choice_scores={
                "excellent": 1.0,
                "good": 0.75,
                "adequate": 0.5,
                "poor": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )
        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )
        return super()._run_eval_sync(output, expected, **kwargs)


@pytest.mark.django_db
async def eval_survey_analysis(call_survey_analysis_tool, pytestconfig):
    """
    Evaluation for survey response analysis functionality.
    """
    await MaxPublicEval(
        experiment_name="survey_analysis",
        task=call_survey_analysis_tool,
        scores=[
            TestDataDetectionScorer(),
            ThemeExtractionQualityScorer(),
            RecommendationQualityScorer(),
        ],
        data=[
            # Test Case 1: Clear test data detection (20 responses)
            EvalCase(
                input={
                    "survey_index": 0,
                    "formatted_responses": generate_test_data_responses(),
                },
                expected={
                    "data_type": "test",
                    "should_detect_test_data": True,
                },
                metadata={"test_type": "test_data_detection"},
            ),
            # Test Case 2: Mixed test and genuine data (25 responses - 60% test, 40% genuine)
            EvalCase(
                input={
                    "survey_index": 1,
                    "formatted_responses": generate_mixed_data_responses(),
                },
                expected={
                    "data_type": "mixed",
                    "expected_themes": ["Interface/Navigation Issues", "Performance Problems"],
                },
                metadata={"test_type": "mixed_data"},
            ),
            # Test Case 3: Genuine positive feedback (20 responses across multiple themes)
            EvalCase(
                input={
                    "survey_index": 2,
                    "formatted_responses": generate_positive_feedback_responses(),
                },
                expected={
                    "data_type": "genuine",
                    "expected_themes": [
                        "User Interface & Design",
                        "Performance & Reliability",
                        "Customer Support",
                        "Integration & Workflow",
                    ],
                },
                metadata={"test_type": "positive_feedback"},
            ),
            # Test Case 4: Genuine negative feedback (18 responses across problem areas)
            EvalCase(
                input={
                    "survey_index": 3,
                    "formatted_responses": generate_negative_feedback_responses(),
                },
                expected={
                    "data_type": "genuine",
                    "expected_themes": [
                        "Performance & Reliability",
                        "Customer Support Issues",
                        "Pricing & Value Concerns",
                        "Missing Features",
                    ],
                },
                metadata={"test_type": "negative_feedback"},
            ),
            # Test Case 5: Multiple questions with varied feedback (32 total responses)
            EvalCase(
                input={
                    "survey_index": 4,
                    "formatted_responses": generate_multi_question_responses(),
                },
                expected={
                    "data_type": "genuine",
                    "expected_themes": [
                        "Ease of Use & Design",
                        "Reliability & Performance",
                        "Advanced Feature Requests",
                        "Mobile & Technical Improvements",
                    ],
                },
                metadata={"test_type": "multi_question_feedback"},
            ),
            # Test Case 6: Support and service feedback (18 responses)
            EvalCase(
                input={
                    "survey_index": 5,
                    "formatted_responses": generate_service_feedback_responses(),
                },
                expected={
                    "data_type": "genuine",
                    "expected_themes": [
                        "Excellent Service",
                        "Response Time Issues",
                        "Knowledge Gaps",
                        "Communication Problems",
                    ],
                },
                metadata={"test_type": "service_feedback"},
            ),
            # Test Case 7: Feature requests and product development feedback (22 responses)
            EvalCase(
                input={
                    "survey_index": 6,
                    "formatted_responses": generate_feature_request_responses(),
                },
                expected={
                    "data_type": "genuine",
                    "expected_themes": [
                        "Integration Requests",
                        "Mobile Improvements",
                        "Analytics & Reporting",
                        "User Experience Enhancements",
                    ],
                },
                metadata={"test_type": "feature_requests"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
