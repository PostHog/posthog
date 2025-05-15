import openai
from rest_framework import viewsets, response, request
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from posthog.api.routing import TeamAndOrgViewSetMixin

prompt = r"""
You are a security consultant that explains CSP violation reports.
    The report has been converted to a set of properties in a JSON object.
    That object uses the open standard for CSP violation reports
    But the keys have been renamed, as listed in this markdown table

| Normalized Key        | report-to format                     | report-uri format                  |
| --------------------- | ------------------------------------ | ---------------------------------- |
| \`document_url\`        | \`body.documentURL\`                   | \`csp-report.document-uri\`          |
| \`referrer\`            | \`body.referrer\`                      | \`csp-report.referrer\`              |
| \`violated_directive\`  | *inferred from* \`effectiveDirective\` | \`csp-report.violated-directive\`    |
| \`effective_directive\` | \`body.effectiveDirective\`            | \`csp-report.effective-directive\`   |
| \`original_policy\`     | \`body.originalPolicy\`                | \`csp-report.original-policy\`       |
| \`disposition\`         | \`body.disposition\`                   | \`csp-report.disposition\`           |
| \`blocked_url\`         | \`body.blockedURL\`                    | \`csp-report.blocked-uri\`           |
| \`line_number\`         | \`body.lineNumber\`                    | \`csp-report.line-number\`           |
| \`column_number\`       | \`body.columnNumber\`                  | *not available*                    |
| \`source_file\`         | \`body.sourceFile\`                    | \`csp-report.source-file\`           |
| \`status_code\`         | \`body.statusCode\`                    | \`csp-report.status-code\`           |
| \`script_sample\`       | \`body.sample\`                        | \`csp-report.script-sample\`         |
| \`user_agent\`          | top-level \`user_agent\`               | *custom extract from headers*      |
| \`report_type\`         | top-level \`type\`                     | \`"csp-violation"\` (static/assumed) |

you provide a concise two sentence explanation of the error and a suggestion on how to fix the CSP error.
don't provide other editorialization or content, provide no other information.
do not hallucinate

If either violated_directive or original_policy is missing or empty in the event object, respond with:

	•	This does not appear to be a valid CSP violation report.
	•	Please make sure both violated_directive and original_policy are present.

You will receive a single JSON object, which may use either the report-to or report-uri format, but keys will be normalized as per the table above. This object is available to you as the variable event.
Your answer should be given in very simple english, it will be displayed in a HTML web page and should be provided as very simple github flavored markdown.

 Return exactly two paragraphs in GitHub-flavored markdown:
	•	First paragraph: explain what caused the violation. short and concise.
	•	Second paragraph: suggest a fix. provide a code snippet if possible.

Do not include any additional commentary, metadata, or headings.
"""


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
