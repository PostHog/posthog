from typing import Any, Literal

from pydantic import BaseModel, Field

from posthog.schema import AgentMode

from products.synthetic_users.backend.models.session import Session

from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.toolkit import AgentToolkit
from ee.hogai.tool import MaxTool
from ee.hogai.tools.browser import COMPUTER_TOOL_DEFINITION, BrowserNavigateTool
from ee.hogai.tools.todo_write import TodoWriteExample

POSITIVE_EXAMPLE_SIGNUP_FLOW = """
User: Go to app.example.com and try to sign up as a new user. Tell me about your experience.
Assistant: I'll test the signup flow as a new user would experience it. Let me create a todo list to track my journey.
*Creates todo list with the following items:*
1. Go to the website and see what's on the homepage
2. Find and click the sign up option
3. Fill out the registration form
4. Complete the signup process
5. Share my experience and any issues I found
*Begins working on the first task*

*Uses browser_navigate to visit app.example.com*
*Uses computer with action='screenshot' to see what's on the homepage*

I've arrived at the homepage. I can see a navigation bar at the top with a "Sign Up" button on the right side. The page has a hero section explaining the product. Let me click on Sign Up...

*Uses computer with action='left_click' at the coordinates of the Sign Up button*
*Uses computer with action='screenshot' to see the signup form*

I'm now on the signup page. I see a form asking for email, password, and name. Let me fill this out by clicking on the email field first...

*Uses computer with action='left_click' on the email field*
*Uses computer with action='type' with text='testuser@example.com'*
""".strip()

POSITIVE_EXAMPLE_SIGNUP_FLOW_REASONING = """
The assistant used the todo list because:
1. Testing a signup flow involves multiple steps that need to be tracked
2. The assistant is acting as a real user would, describing their experience
3. Each step involves looking at the page via screenshots and interacting naturally
4. The todo list ensures comprehensive coverage of the user journey
""".strip()

POSITIVE_EXAMPLE_BUG_REPRODUCTION = """
User: A user reported that they can't submit the contact form on oursite.com. Can you try to reproduce this issue?
Assistant: I'll try to reproduce this contact form issue by going through the same steps a user would. Let me track my investigation.
*Creates todo list with the following items:*
1. Navigate to the contact page
2. Take a screenshot to understand the form layout
3. Fill out the form with test data
4. Try to submit and observe what happens
5. Report my findings
*Begins working on the first task*

*Uses browser_navigate to visit oursite.com/contact*
*Uses computer with action='screenshot' to see the contact form*

I'm on the contact page. I see a form with Name, Email, Subject, and Message fields. There's a blue "Send Message" button at the bottom. Let me fill this out by clicking on the Name field...

*Uses computer with action='left_click' on the Name field coordinates*
*Uses computer with action='type' with text='Test User'*
*Uses computer with action='key' with key='Tab' to move to the next field*
*Uses computer with action='type' with text='test@example.com'*

Let me continue filling out the form and then click submit...

*Uses computer with action='left_click' on the Send Message button*
*Uses computer with action='screenshot' to see what happened*

Interesting! After clicking submit, I see a red error message that says "Please complete the captcha" but I don't see any captcha on the form. This could be the bug - the captcha might not be loading properly.
""".strip()

POSITIVE_EXAMPLE_BUG_REPRODUCTION_REASONING = """
The assistant used the todo list because:
1. Bug reproduction requires methodical step-by-step testing
2. The assistant is experiencing the site as a user would
3. Screenshots at each step help identify where issues occur
4. The todo list documents the investigation process
""".strip()

POSITIVE_EXAMPLE_UX_FEEDBACK = """
User: Please use our checkout flow at shop.example.com and give me feedback on the user experience. Add something to cart and go through checkout.
Assistant: I'll go through your checkout flow as a new customer would and provide honest UX feedback. Let me track my journey.
*Creates todo list with the following items:*
1. Browse the shop and find a product
2. Add an item to cart
3. Go to checkout
4. Fill out checkout information
5. Review the process and share UX feedback
*Begins working on the first task*

*Uses browser_navigate to visit shop.example.com*
*Uses computer with action='screenshot' to see the shop*

First impression: The homepage loads and I can see a clean layout with product categories. The navigation is clear. I'll click on a product category to browse...

*Uses computer with action='left_click' on a product category*
*Uses computer with action='screenshot' to see the products*
*Uses computer with action='left_click' on the first product*
*Uses computer with action='screenshot' to see product details*

I'm on a product page. I can see the price ($29.99), product images, and an "Add to Cart" button. The button is prominent and easy to find - good UX. Let me add this to cart...

*Uses computer with action='left_click' on the Add to Cart button*
*Uses computer with action='screenshot' to see what happens*

Feedback: After clicking Add to Cart, a small popup appeared briefly but disappeared too quickly. I'm not 100% sure if it was added. This could cause user uncertainty. I'll check the cart by clicking the cart icon...
""".strip()

POSITIVE_EXAMPLE_UX_FEEDBACK_REASONING = """
The assistant used the todo list because:
1. UX testing requires going through a complete user journey
2. The assistant provides feedback at each step like a real tester
3. Screenshots capture the visual state for analysis
4. The structured approach ensures all parts of the flow are tested
""".strip()


class TaskResultToolArgs(BaseModel):
    experience_writeup: str = Field(
        description="A detailed writeup of your experience completing the task.",
    )
    key_insights: list[str] = Field(
        description="A list of key insights from the experience.",
    )
    sentiment: Literal["positive", "neutral", "negative"] = Field(
        description="The sentiment of the experience. Must be one of: positive, neutral, negative.",
    )


class TaskResultTool(MaxTool):
    name: Literal["task_result"] = "task_result"
    description: str = "Use this tool to return the results of your experience completing the task."
    args_schema: type[BaseModel] = TaskResultToolArgs

    async def _arun_impl(
        self, experience_writeup: str, key_insights: list[str], sentiment: Literal["positive", "neutral", "negative"]
    ) -> tuple[str, Any]:
        trace_id = self._get_trace_id(self._config)
        session = await Session.objects.aget(id=trace_id)

        session.experience_writeup = experience_writeup
        session.key_insights = key_insights
        session.sentiment = sentiment
        await session.asave(update_fields=["experience_writeup", "key_insights", "sentiment"])

        return "Task result", {
            "experience_writeup": experience_writeup,
            "key_insights": key_insights,
            "sentiment": sentiment,
        }


class SyntheticUserAgentToolkit(AgentToolkit):
    POSITIVE_TODO_EXAMPLES = [
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_SIGNUP_FLOW,
            reasoning=POSITIVE_EXAMPLE_SIGNUP_FLOW_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_BUG_REPRODUCTION,
            reasoning=POSITIVE_EXAMPLE_BUG_REPRODUCTION_REASONING,
        ),
        TodoWriteExample(
            example=POSITIVE_EXAMPLE_UX_FEEDBACK,
            reasoning=POSITIVE_EXAMPLE_UX_FEEDBACK_REASONING,
        ),
    ]

    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [
            BrowserNavigateTool,
            TaskResultTool,
        ]

    @property
    def native_tools(self) -> list[dict[str, Any]]:
        """Native Anthropic tools that are passed directly to bind_tools."""
        return [
            COMPUTER_TOOL_DEFINITION,
        ]


synthetic_user_agent = AgentModeDefinition(
    mode=AgentMode.BROWSER_USE,
    mode_description="Specialized mode for synthetic users navigating websites and providing insights about user behavior.",
    toolkit_class=SyntheticUserAgentToolkit,
)
