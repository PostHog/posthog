from django.http import JsonResponse
import requests
from posthog.api.utils import get_token
from posthog.exceptions import generate_exception_response
from rest_framework.request import Request
from rest_framework import status


from posthog.models.team.team import Team
from django.views.decorators.csrf import csrf_exempt

from posthog.utils_cors import cors_response


@csrf_exempt
def support_tickets(request: Request):
    token = get_token(None, request)

    if not token:
        return cors_response(
            request,
            generate_exception_response(
                "support_tickets",
                "API key not provided. You can find your project API key in PostHog project settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    # TODO: fix organization_id & other fields don't exist in the cached object
    # team = Team.objects.get_team_from_cache_or_token(token)
    team = Team.objects.get(api_token=token)
    if team is None:
        return cors_response(
            request,
            generate_exception_response(
                "support_tickets",
                "Project API key invalid. You can find your project API key in PostHog project settings.",
                type="authentication_error",
                code="invalid_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )
    zendesk_key = team.zendesk_key
    if zendesk_key is None:
        return cors_response(
            request,
            generate_exception_response(
                "support_tickets",
                "Zendesk API key not set. You can set it in PostHog project integrations settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,  # probably should be some other error
            ),
        )

    user = request.GET.get("user")
    validation_token = request.GET.get("validation_token")

    organization_id = team.organization_id

    headers = {"Authorization": f"Basic {zendesk_key}"}
    response = requests.request(
        "GET",
        "https://posthoghelp.zendesk.com/api/v2/organizations/search",
        data="",
        headers=headers,
        params={"external_id": organization_id},
    )

    zendesk_orgs = response.json()

    # if len(zendesk_orgs["organizations"]) == 0:
    #     return JsonResponse({"error": "No organization found with that ID"}, status=404)

    # if zendesk_orgs["organizations"][0]["external_id"] != organization_id:
    #     return JsonResponse({"error": "Something weird is going on"}, status=404)

    # zendesk_org_id = zendesk_orgs["organizations"][0]["id"]
    zendesk_org_id = "123"

    return cors_response(
        request,
        JsonResponse(
            {
                "supportTickets": {
                    "x": user,
                    "y": validation_token,
                    "zendesk_org_id": zendesk_org_id,
                    "org": organization_id,
                    "zdorgs": zendesk_orgs,
                    "zendesk_key": zendesk_key,
                    "team": dir(team),
                }
            }
        ),
    )


# def get_zendesk_tickets(request):
#     try:
#         body = json.loads(request.body)
#     except (TypeError, json.decoder.JSONDecodeError):
#         return JsonResponse({"error": "Cannot parse request body"}, status=400)


#     response = requests.request(
#         "GET",
#         "https://posthoghelp.zendesk.com/api/v2/organizations/search",
#         data="",
#         headers=headers,
#         params={"external_id": body.get("org_id")},
#     )

#     zendesk_orgs = response.json()

#     if len(zendesk_orgs["organizations"]) == 0:
#         return JsonResponse({"error": "No organization found with that ID"}, status=404)

#     if zendesk_orgs["organizations"][0]["external_id"] != body.get("org_id"):
#         return JsonResponse({"error": "Something weird is going on"}, status=404)

#     zendesk_org_id = zendesk_orgs["organizations"][0]["id"]

#     # get all tickets from that org
#     tickets = requests.request(
#         "GET",
#         f"https://posthoghelp.zendesk.com/api/v2/organizations/{zendesk_org_id}/tickets",
#         data="",
#         headers=headers,
#     )

#     def filter_tickets(tickets):
#         current_time = datetime.now()
#         return [
#             ticket
#             for ticket in tickets
#             if (current_time - datetime.strptime(ticket["updated_at"], "%Y-%m-%dT%H:%M:%SZ")).total_seconds() < 604800
#             or ticket["status"] not in ["solved", "closed"]
#         ]

#     return JsonResponse({"tickets": filter_tickets(tickets.json()["tickets"])})


# def reply_zendesk_ticket(request):
#     # do auth
#     email = "marcus.h@posthog.com"

#     try:
#         body = json.loads(request.body)
#     except (TypeError, json.decoder.JSONDecodeError):
#         return JsonResponse({"error": "Cannot parse request body"}, status=400)

#     headers = {"Authorization": "Basic TOKEN"}

#     author = requests.request(
#         "GET", "https://posthoghelp.zendesk.com/api/v2/users/search", json={"query": f"email:{email}"}, headers=headers
#     ).json()
#     author_id = author["users"][0]["id"]

#     ticket_id = body.get("ticket_id")
#     comment_body = body.get("comment")["body"]

#     tickets = requests.request(
#         "PUT",
#         f"https://posthoghelp.zendesk.com/api/v2/tickets/{ticket_id}.json",
#         json={"ticket": {"comment": {"body": comment_body, "public": True, "author_id": author_id}}},
#         headers=headers,
#     )

#     return JsonResponse({"tickets": tickets.json()})


# @authenticate_secondarily
# def create_new_zendesk_ticket(request):
#     try:
#         body = json.loads(request.body)
#     except (TypeError, json.decoder.JSONDecodeError):
#         return JsonResponse({"error": "Cannot parse request body"}, status=400)

#     payload = {
#         "request": {
#             "requester": {"name": body.get("name"), "email": body.get("email")},
#             "subject": body.get("subject"),
#             "custom_fields": [
#                 {"id": 22084126888475, "value": body.get("severity_level")},
#                 {"id": 22129191462555, "value": body.get("distinct_id")},
#             ],
#             "comment": {
#                 "body": body.get("body"),
#             },
#         },
#     }

#     response = requests.request("POST", "https://posthoghelp.zendesk.com/api/v2/requests.json", json=payload).json()

#     return JsonResponse({"response": response})


# @authenticate_secondarily
# def close_zendesk_ticket(request):
#     # do auth
#     org_id = ""
#     requester_id = 19444577233435

#     try:
#         body = json.loads(request.body)
#     except (TypeError, json.decoder.JSONDecodeError):
#         return JsonResponse({"error": "Cannot parse request body"}, status=400)

#     headers = {"Authorization": "Basic TOKEN"}

#     ticket_id = body.get("ticket_id")
#     ticket = requests.request(
#         "GET", f"https://posthoghelp.zendesk.com/api/v2/tickets/{ticket_id}.json", data="", headers=headers
#     ).json()

#     if ticket["ticket"]["organization_id"] != org_id and ticket["ticket"]["requester_id"] != requester_id:
#         return JsonResponse({"error": "You are not authorized to close this ticket"}, status=403)

#     requests.request(
#         "PUT",
#         f"https://posthoghelp.zendesk.com/api/v2/tickets/{ticket_id}.json",
#         json={"ticket": {"status": "solved"}},
#         headers=headers,
#     )

#     return JsonResponse({"ticket": ticket})
