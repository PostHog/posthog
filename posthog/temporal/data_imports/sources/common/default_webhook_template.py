from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="warehouse_source_webhook",
    id="template-warehouse-source-default",
    name="Default warehouse source webhook",
    description="Passthrough webhook that returns the request body as-is",
    icon_url="/static/services/webhook.png",
    category=["Data warehouse"],
    code_language="hog",
    code="return request.body",
    inputs_schema=[],
)
