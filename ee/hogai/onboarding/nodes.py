from typing import Any

from pydantic import BaseModel

from ee.hogai.core.loop_graph.nodes import AgentExecutable
from ee.hogai.utils.types.base import AssistantState


class OnboardingStepState(BaseModel):
    """Tracks the current state of the onboarding process"""

    current_step: str | None = None
    product_key: str | None = None
    completed_steps: list[str] = []
    step_data: dict[str, Any] = {}


class OnboardingAgentNode(AgentExecutable):
    """
    Specialized node for onboarding conversations.
    Tracks onboarding progress and generates contextual questions with button options.
    """

    SYSTEM_PROMPT = """You are a friendly onboarding assistant helping a new PostHog user get set up with their product.

Your role is to guide them through the onboarding steps in a conversational way. You can:
- Ask questions about their setup and preferences
- Provide clear explanations of what each step involves
- Offer button options for quick selections, but also understand natural language responses
- Track their progress and move them to the next step when ready

Be helpful, concise, and encouraging. Make the onboarding process feel easy and conversational.

Current onboarding context will be provided in the conversation state.
"""

    def get_onboarding_state(self, state: AssistantState) -> OnboardingStepState:
        """Extract onboarding state from conversation state"""
        onboarding_data = state.get("onboarding_state", {})
        return OnboardingStepState(**onboarding_data) if onboarding_data else OnboardingStepState()

    def update_onboarding_state(self, state: AssistantState, onboarding_state: OnboardingStepState) -> AssistantState:
        """Update onboarding state in conversation state"""
        state["onboarding_state"] = onboarding_state.model_dump()
        return state

    def get_product_onboarding_steps(self, product_key: str) -> list[dict[str, Any]]:
        """
        Get the onboarding steps for a specific product.
        Maps to the same steps as the existing onboarding flow.
        """
        # Product-specific step configurations based on existing onboarding
        # These mirror the steps in frontend/src/scenes/onboarding/Onboarding.tsx

        common_steps = [
            {
                "key": "install",
                "title": "Install PostHog",
                "question": "Which SDK would you like to use to install PostHog?",
                "type": "sdk_selection",
            },
        ]

        product_specific_steps = {
            "product_analytics": [
                {
                    "key": "product_configuration",
                    "title": "Configure features",
                    "question": "Which features would you like to enable for product analytics?",
                    "type": "feature_toggles",
                    "options": [
                        {"key": "autocapture_opt_out", "label": "Autocapture", "default": True},
                        {"key": "capture_performance_opt_in", "label": "Performance monitoring", "default": False},
                    ],
                },
                {
                    "key": "session_replay",
                    "title": "Session replay configuration",
                    "question": "Would you like to enable session replay?",
                    "type": "boolean",
                    "options": [{"label": "Yes", "value": True}, {"label": "No", "value": False}],
                },
            ],
            "session_replay": [
                {
                    "key": "product_configuration",
                    "title": "Configure session replay",
                    "question": "How would you like to configure session replay?",
                    "type": "feature_toggles",
                    "options": [
                        {"key": "session_recording_opt_in", "label": "Enable session recordings", "default": True},
                        {
                            "key": "capture_console_log_opt_in",
                            "label": "Capture console logs",
                            "default": False,
                        },
                    ],
                },
            ],
            "feature_flags": [
                {
                    "key": "reverse_proxy",
                    "title": "Reverse proxy setup",
                    "question": "Would you like to set up a reverse proxy? This helps avoid ad blockers.",
                    "type": "optional",
                },
            ],
            "web_analytics": [
                {
                    "key": "authorized_domains",
                    "title": "Authorized domains",
                    "question": "Which domains should be authorized for web analytics?",
                    "type": "text_list",
                },
                {
                    "key": "product_configuration",
                    "title": "Configure features",
                    "question": "Which web analytics features would you like to enable?",
                    "type": "feature_toggles",
                    "options": [
                        {"key": "autocapture_opt_out", "label": "Autocapture", "default": True},
                        {"key": "heatmaps_opt_in", "label": "Heatmaps", "default": False},
                    ],
                },
            ],
            "error_tracking": [
                {
                    "key": "source_maps",
                    "title": "Source maps",
                    "question": "Would you like to upload source maps for better error tracking?",
                    "type": "optional",
                },
                {
                    "key": "alerts",
                    "title": "Configure alerts",
                    "question": "How would you like to be notified about errors?",
                    "type": "text",
                },
            ],
        }

        # Common final steps for all products
        final_steps = [
            {
                "key": "ai_consent",
                "title": "AI features",
                "question": "Would you like to enable AI-powered features in PostHog?",
                "type": "boolean",
                "options": [{"label": "Yes", "value": True}, {"label": "No, thanks", "value": False}],
            },
            {
                "key": "invite_teammates",
                "title": "Invite teammates",
                "question": "Would you like to invite teammates to your project?",
                "type": "optional",
            },
        ]

        steps = common_steps + product_specific_steps.get(product_key, []) + final_steps
        return steps

    def get_current_step_info(self, state: AssistantState) -> dict[str, Any] | None:
        """Get information about the current onboarding step"""
        onboarding_state = self.get_onboarding_state(state)

        if not onboarding_state.product_key:
            return None

        steps = self.get_product_onboarding_steps(onboarding_state.product_key)

        # Find the next incomplete step
        for step in steps:
            if step["key"] not in onboarding_state.completed_steps:
                return step

        return None  # All steps completed
