from rest_framework.permissions import IsAuthenticated
from posthog.api.routing import TeamAndOrgViewSetMixin
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import status


class MessageSetupViewSet(TeamAndOrgViewSetMixin):
    permission_classes = [IsAuthenticated]

    @action(methods=["POST"], detail=False)
    def request_account(self, request, **kwargs):
        """Request a messaging account with a specified email domain."""

        #  Steps:
        # 1. Create a new API key for project: https://dev.mailjet.com/email/reference/settings/api-key-configuration/#v3_post_apikey
        # 2. Store the API key in the integration for the project
        # 3. Use the project's API key to create a sender for the domain from request body, using *@yourdomain.com for the email: https://dev.mailjet.com/email/reference/sender-addresses-and-domains/sender/#v3_post_sender
        # 4. Do a GET on /dns/{domain_ID or domain_name} to retrieve the values you need for the DNS record.

        email_domain = request.data.get("email_domain")

        if not email_domain:
            return Response({"error": "email_domain is required"}, status=status.HTTP_400_BAD_REQUEST)

        # TODO: Implement actual account request logic
        return Response(
            {
                "status": "pending",
                "dns_records": {
                    "dkim": {
                        "record_name": dkim_record_name,
                        "record_value": dkim_record_value,
                        "status": dkim_status,
                    },
                    "spf": {
                        "record_value": spf_record_value,
                        "status": spf_status,
                    },
                },
            }
        )

    @action(methods=["GET"], detail=False)
    def verify_domain(self, request, **kwargs):
        """Verify the email domain for messaging setup."""

        # Do a GET on /dns/{domain_ID or domain_name} to retrieve the values you need for the DNS record.
        # This endpoint also returns the current status of the DKIM and SPF records.

        domain = request.query_params.get("domain")

        if not domain:
            return Response({"error": "Domain parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        # TODO: Implement actual domain verification logic

        return Response(
            {
                "status": "pending",  # pending, verified
                "dns_records": {
                    "dkim": {
                        "record_name": dkim_record_name,
                        "record_value": dkim_record_value,
                        "status": dkim_status,
                    },
                    "spf": {
                        "record_value": spf_record_value,
                        "status": spf_status,
                    },
                },
            }
        )
