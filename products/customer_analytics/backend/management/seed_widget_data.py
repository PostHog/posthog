from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import TypedDict
from uuid import UUID

from django.utils import timezone

from posthog.models.comment import Comment
from posthog.models.team import Team
from posthog.models.user import User

from products.conversations.backend.models import (
    EMAIL_THREAD_COMMENT_SCOPE,
    EmailThread,
    EmailThreadAccountLink,
    EmailThreadMessage,
    EmailThreadMessageDirection,
    EmailThreadParticipant,
    EmailThreadParticipantKind,
)
from products.conversations.backend.models.ticket import Ticket
from products.customer_analytics.backend.models import Account, AccountChannelSummary, Meeting, MeetingParticipant
from products.customer_analytics.backend.models.account_channel_summary import SlackSummaryCadence
from products.customer_analytics.backend.models.meeting import MeetingResponseStatus, MeetingStatus
from products.product_analytics.backend.facade import api as product_analytics
from products.product_analytics.backend.facade.enums import InsightVariableType
from products.product_analytics.backend.facade.models import Insight

WIDGET_ACCOUNT_COUNT = 5


class InsightVariablePayload(TypedDict):
    variableId: str
    code_name: str
    value: str


BILLING_INSIGHT_SHORT_IDS = {
    "usage": "fiJDsKLp",
    "spend_history": "o4I9sdFE",
    "spend_by_product": "Tjo4bsux",
}

USAGE_SQL = """SELECT
    today() - number AS date,
    800 + cityHash64(toString({variables.billing_org_id})) % 500 + number * 7 AS Events,
    120 + cityHash64(toString({variables.billing_org_id})) % 90 + number * 2 AS `Identified Events`,
    300 + cityHash64(toString({variables.billing_org_id})) % 150 + number * 3 AS `Feature Flag Requests`,
    20 + cityHash64(toString({variables.billing_org_id})) % 30 + number AS Recordings,
    5 + cityHash64(toString({variables.billing_org_id})) % 8 + number % 4 AS `Survey Responses`
FROM numbers(31)
WHERE today() - number >= toDate({variables.billing_start_date})
  AND today() - number <= toDate({variables.billing_end_date})
ORDER BY date"""

SPEND_HISTORY_SQL = """SELECT
    toStartOfMonth(today()) - toIntervalMonth(number) AS period,
    1800 + cityHash64(toString({variables.billing_org_id})) % 700 + number * 55 AS confirmed_MRR,
    if(number % 4 = 0, 120 + number * 5, 0) AS credits_used,
    1950 + cityHash64(toString({variables.billing_org_id})) % 750 + number * 60 AS forecasted_MRR,
    if(number = 10, 75, 0) AS refunded
FROM numbers(13)
WHERE period >= toStartOfMonth(toDate({variables.billing_start_date}))
  AND period <= toStartOfMonth(toDate({variables.billing_end_date}))
ORDER BY period"""

SPEND_BY_PRODUCT_SQL = """SELECT
    toStartOfMonth(today()) - toIntervalMonth(intDiv(number, 3)) AS month,
    multiIf(
        number % 3 = 0, 'Product analytics',
        number % 3 = 1, 'Session replay',
        'Feature flags'
    ) AS cleaned_description,
    120 + cityHash64(toString({variables.billing_org_id})) % 90
        + intDiv(number, 3) * 12
        + (number % 3) * 45 AS total_amount
FROM numbers(39)
WHERE month >= toStartOfMonth(toDate({variables.billing_start_date}))
  AND month <= toStartOfMonth(toDate({variables.billing_end_date}))
ORDER BY month, cleaned_description"""


def seed_widget_data(
    *,
    team: Team,
    accounts: list[Account],
    created_account_ids: set[UUID],
    user_pool: list[User],
    output: Callable[[str], None],
    account_count: int = WIDGET_ACCOUNT_COUNT,
) -> None:
    if account_count < 0:
        raise ValueError("account_count must not be negative")

    creator = team.organization.members.first()
    _seed_billing_insights(team=team, creator=creator, accounts=accounts)

    selected_accounts = accounts[:account_count]
    for index, account in enumerate(selected_accounts, start=1):
        manager = user_pool[(index - 1) % len(user_pool)] if user_pool else creator
        if account.id in created_account_ids:
            _seed_account_contact_data(account=account, index=index)
        _seed_meetings(team=team, account=account, manager=manager, index=index)
        _seed_email_thread(team=team, account=account, manager=manager, index=index)
        _seed_support_ticket(team=team, account=account, index=index)
        _seed_channel_summary(team=team, account=account, index=index)

    output(f"Seeded billing insights and widget data for {len(selected_accounts)} account(s).")


def _ensure_billing_variables(team: Team, accounts: list[Account]) -> dict[str, InsightVariablePayload]:
    today = timezone.now().date()
    default_org = accounts[0].external_id if accounts and accounts[0].external_id else "example-account"
    specs = {
        "billing_org_id": ("Billing organization", InsightVariableType.STRING, default_org),
        "billing_start_date": ("Billing start date", InsightVariableType.DATE, str(today - timedelta(days=365))),
        "billing_end_date": ("Billing end date", InsightVariableType.DATE, str(today)),
    }
    existing = {
        variable.code_name: variable
        for variable in product_analytics.insight_variables_by_code_names(team.id, specs.keys())
        if variable.code_name
    }
    variables: dict[str, InsightVariablePayload] = {}
    for code_name, (name, variable_type, default_value) in specs.items():
        variable = existing.get(code_name)
        if variable is None:
            variable = product_analytics.create_insight_variable(
                team_id=team.id,
                name=name,
                type=variable_type,
                code_name=code_name,
                default_value=default_value,
            )
        variables[str(variable.id)] = {
            "variableId": str(variable.id),
            "code_name": code_name,
            "value": default_value,
        }
    return variables


def _seed_billing_insights(*, team: Team, creator: User | None, accounts: list[Account]) -> None:
    variables = _ensure_billing_variables(team, accounts)
    usage_columns = [
        "Events",
        "Identified Events",
        "Feature Flag Requests",
        "Recordings",
        "Survey Responses",
    ]
    currency_format = {"style": "number", "prefix": "$", "suffix": "", "decimalPlaces": 2}
    insight_specs = [
        (
            BILLING_INSIGHT_SHORT_IDS["usage"],
            "Billing usage by metric (warehouse)",
            "Daily billing usage for a selected organization.",
            {
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": USAGE_SQL, "variables": variables},
                "display": "Auto",
                "chartSettings": {
                    "xAxis": {"column": "date"},
                    "yAxis": [{"column": column} for column in usage_columns],
                    "chartStyle": {"curve": "smooth"},
                    "showLegend": True,
                    "legendPosition": "bottom",
                },
                "tableSettings": {"columns": [{"column": "date"}, *({"column": column} for column in usage_columns)]},
            },
        ),
        (
            BILLING_INSIGHT_SHORT_IDS["spend_history"],
            "Billing history with credits/refunds",
            "Monthly billing history with forecast, credits, and refunds.",
            {
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": SPEND_HISTORY_SQL, "variables": variables},
                "display": "ActionsStackedBar",
                "chartSettings": {
                    "xAxis": {"column": "period"},
                    "yAxis": [
                        {"column": column, "settings": {"formatting": currency_format}}
                        for column in ("confirmed_MRR", "credits_used", "forecasted_MRR", "refunded")
                    ],
                    "showNullsAsZero": True,
                },
            },
        ),
        (
            BILLING_INSIGHT_SHORT_IDS["spend_by_product"],
            "Per product spend for credited invoices/startup",
            "Monthly spend split across products.",
            {
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": SPEND_BY_PRODUCT_SQL, "variables": variables},
                "display": "ActionsStackedBar",
                "chartSettings": {
                    "xAxis": {"column": "month"},
                    "yAxis": [{"column": "total_amount", "settings": {"formatting": currency_format}}],
                    "seriesBreakdownColumn": "cleaned_description",
                },
            },
        ),
    ]
    for short_id, name, description, query in insight_specs:
        Insight.objects_including_soft_deleted.get_or_create(
            team=team,
            short_id=short_id,
            defaults={
                "name": name,
                "description": description,
                "query": query,
                "saved": True,
                "deleted": False,
                "created_by": creator,
                "last_modified_by": creator,
            },
        )


def _seed_account_contact_data(*, account: Account, index: int) -> None:
    domain = f"customer-{index}.example.com"
    account.properties = account.properties.model_copy(
        update={
            "website_domain": domain,
            "email_domains": [domain],
            "known_emails": [f"champion@{domain}", f"finance@{domain}"],
            "slack_channel_id": f"CSEED{index:04d}",
        }
    )
    account.slack_summary_cadence = SlackSummaryCadence.WEEKLY
    account.save(update_fields=["_properties", "slack_summary_cadence", "updated_at"])


def _seed_meetings(*, team: Team, account: Account, manager: User | None, index: int) -> None:
    now = timezone.now()
    meetings = [
        ("quarterly-review", "Quarterly business review", now - timedelta(days=3), MeetingStatus.CONFIRMED),
        ("implementation", "Implementation check-in", now + timedelta(days=4), MeetingStatus.TENTATIVE),
    ]
    for suffix, title, start_time, status in meetings:
        meeting, _ = Meeting.objects.for_team(team.id).update_or_create(
            team=team,
            ical_uid=f"customer-analytics-seed-{account.id}-{suffix}",
            recurrence_instance_id="",
            defaults={
                "account": account,
                "title": title,
                "description": "Customer analytics development fixture",
                "start_time": start_time,
                "end_time": start_time + timedelta(minutes=45),
                "organizer_email": manager.email if manager else "account-manager@example.com",
                "status": status,
            },
        )
        participants = [
            (f"champion@customer-{index}.example.com", "Customer champion", MeetingResponseStatus.ACCEPTED, False),
            (
                manager.email if manager else "account-manager@example.com",
                manager.first_name if manager else "Account manager",
                MeetingResponseStatus.ACCEPTED,
                True,
            ),
            (f"finance@customer-{index}.example.com", "Finance partner", MeetingResponseStatus.TENTATIVE, False),
        ]
        for email, display_name, response_status, is_organizer in participants:
            MeetingParticipant.objects.for_team(team.id).update_or_create(
                team=team,
                meeting=meeting,
                email=email,
                defaults={
                    "display_name": display_name,
                    "response_status": response_status,
                    "is_organizer": is_organizer,
                },
            )


def _seed_email_thread(*, team: Team, account: Account, manager: User | None, index: int) -> None:
    now = timezone.now()
    thread, _ = EmailThread.objects.for_team(team.id).update_or_create(
        team=team,
        canonical_thread_key=f"customer-analytics-seed-{account.id}",
        defaults={
            "subject": "Renewal planning",
            "first_message_at": now - timedelta(days=5),
            "last_message_at": now - timedelta(days=1),
            "message_count": 2,
            "preview": "Could we review next quarter's rollout?",
        },
    )
    EmailThreadAccountLink.objects.for_team(team.id).update_or_create(
        team=team,
        thread=thread,
        account_id=str(account.id),
        defaults={"account_external_id": account.external_id, "match_source": "email_domain"},
    )
    participants = [
        (f"champion@customer-{index}.example.com", "Customer champion", EmailThreadParticipantKind.CUSTOMER),
        (
            manager.email if manager else "account-manager@example.com",
            manager.first_name if manager else "Account manager",
            EmailThreadParticipantKind.INTERNAL,
        ),
    ]
    for email, display_name, kind in participants:
        EmailThreadParticipant.objects.for_team(team.id).update_or_create(
            team=team,
            thread=thread,
            email=email,
            defaults={"display_name": display_name, "kind": kind},
        )
    messages = [
        (
            "customer",
            "Could we review next quarter's rollout and expected usage?",
            now - timedelta(days=5),
            f"champion@customer-{index}.example.com",
            "Customer champion",
            EmailThreadMessageDirection.INBOUND,
        ),
        (
            "manager",
            "Yes. I added a review meeting and a usage summary for the team.",
            now - timedelta(days=1),
            manager.email if manager else "account-manager@example.com",
            manager.first_name if manager else "Account manager",
            EmailThreadMessageDirection.OUTBOUND,
        ),
    ]
    for suffix, content, sent_at, sender_email, sender_name, direction in messages:
        source_id = f"customer-analytics-seed-{account.id}-{suffix}"
        message = (
            EmailThreadMessage.objects.for_team(team.id)
            .filter(team=team, source_type="customer_analytics_seed", source_id=source_id)
            .first()
        )
        if message is None:
            comment = Comment.objects.create(
                team=team,
                scope=EMAIL_THREAD_COMMENT_SCOPE,
                item_id=str(thread.id),
                content=content,
            )
            EmailThreadMessage.objects.for_team(team.id).create(
                team=team,
                thread=thread,
                comment=comment,
                message_id=f"<{source_id}@example.com>",
                sent_at=sent_at,
                sender_email=sender_email,
                sender_name=sender_name,
                to_recipients=[],
                cc_recipients=[],
                direction=direction,
                source_type="customer_analytics_seed",
                source_id=source_id,
            )


def _seed_support_ticket(*, team: Team, account: Account, index: int) -> None:
    session_id = f"ca-seed-{str(account.id)[:48]}"
    ticket = Ticket.objects.filter(team=team, widget_session_id=session_id).first()
    if ticket is None:
        ticket = Ticket.objects.create_with_number(
            team=team,
            widget_session_id=session_id,
            distinct_id="",
            organization_id=account.external_id,
            status="open",
            priority="medium",
            anonymous_traits={
                "name": "Customer champion",
                "email": f"champion@customer-{index}.example.com",
            },
        )
    else:
        ticket.organization_id = account.external_id
        ticket.distinct_id = ""
        ticket.status = "open"
        ticket.priority = "medium"
        ticket.save(update_fields=["organization_id", "distinct_id", "status", "priority", "updated_at"])
    Comment.objects.get_or_create(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content="Could you help us review our workspace configuration?",
        defaults={"item_context": {"author_type": "customer", "is_private": False}},
    )


def _seed_channel_summary(*, team: Team, account: Account, index: int) -> None:
    period_end = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    period_start = period_end - timedelta(days=7)
    summary = (
        AccountChannelSummary.objects.for_team(team.id)
        .filter(
            team=team,
            account=account,
            model_name="customer-analytics-dev-seed",
        )
        .first()
    )
    values = {
        "slack_channel_id": account.properties.slack_channel_id or f"CSEED{index:04d}",
        "cadence": SlackSummaryCadence.WEEKLY,
        "period_start": period_start,
        "period_end": period_end,
        "content": "The team reviewed adoption, rollout timing, and next steps for the account.",
        "message_count": 3,
        "messages": [
            {
                "author": "Customer champion",
                "sent_at": str(period_start + timedelta(days=1)),
                "permalink": "https://example.com/customer-conversation",
            },
            {
                "author": "Account manager",
                "sent_at": str(period_start + timedelta(days=3)),
                "permalink": "https://example.com/account-manager-reply",
            },
            {
                "author": "Customer champion",
                "sent_at": str(period_start + timedelta(days=5)),
                "permalink": "https://example.com/customer-follow-up",
            },
        ],
        "model_name": "customer-analytics-dev-seed",
    }
    if summary is None:
        AccountChannelSummary.objects.for_team(team.id).create(team=team, account=account, **values)
    else:
        for field, value in values.items():
            setattr(summary, field, value)
        summary.save(update_fields=[*values])
