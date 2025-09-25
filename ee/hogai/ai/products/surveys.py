from products.surveys.backend.max_tools import CreateSurveyTool, SurveyAnalysisTool

from ee.hogai.ai.product_base import AIProduct


class SurveysAIProduct(AIProduct):
    name = "surveys"
    routing_prompt = "Use when creating or analyzing surveys."
    # TODO: Populate concise JTBD/workflow system_prompt when product enable/disable is active
    system_prompt = ""
    tools = [
        CreateSurveyTool,
        SurveyAnalysisTool,
    ]
