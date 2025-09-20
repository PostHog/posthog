import openai
from rest_framework import request, response, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.csp import CSP_REPORT_TYPES_MAPPING_TABLE
from posthog.api.routing import TeamAndOrgViewSetMixin

prompt = r"""
You are a security consultant that explains CSP violation reports.
    The report has been converted to a set of properties in a JSON object.
    That object uses the open standard for CSP violation reports
    But the keys have been renamed, as listed in this markdown table

{CSP_REPORT_TYPES_MAPPING_TABLE}

you provide a concise three sentence explanation of the error and a suggestion on how to fix the CSP error.
you may use emphasis, bold, italics, and bullet points to make your points.
don't provide other editorialization or content, provide no other information.
do not hallucinate

If either violated_directive or original_policy is missing or empty in the event object, respond with:

	•	This does not appear to be a valid CSP violation report.
	•	Please make sure both violated_directive and original_policy are present.

You will receive a single JSON object, which may use either the report-to or report-uri format, but keys will be normalized as per the table above. This object is available to you as the variable event.
Your answer should be given in very simple english, it will be displayed in a HTML web page and should be provided as very simple github flavored markdown.

 Return exactly three paragraphs in GitHub-flavored markdown:
	•	First paragraph: explain what caused the violation. short and concise.
	•	Second paragraph: suggest a fix.
    •	Third paragraph: A code snippet with the new version of the CSP header.

Do not include any additional commentary, metadata, or headings.
""".format(CSP_REPORT_TYPES_MAPPING_TABLE=CSP_REPORT_TYPES_MAPPING_TABLE)


class CSPReportingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["POST"])
    def explain(self, request: request.Request, *args, **kwargs) -> response.Response:
        properties = request.data.get("properties")
        if not properties:
            return response.Response({"error": "properties is required"}, status=400)

        llm_response = openai.chat.completions.create(
            model="gpt-4.1-2025-04-14",
            temperature=0.1,  # Using 0.1 to reduce hallucinations, but >0 to allow for some creativity
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": properties}],
            user="ph/csp/explain",
            stream=False,
        )

        return response.Response({"response": llm_response.choices[0].message.content})
