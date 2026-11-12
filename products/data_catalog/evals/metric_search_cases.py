"""Invented metric catalog and labeled search cases for the metric search eval.

Pure data, no Django: the eval suite and the backend regression test seed the same catalog and run the
same cases. The company, the metrics and the queries are invented. Real sessions told us which case
types matter; none of their metric names or queries are here.

Each case has one case type, and the eval reports recall per type, so a lane's gain shows where it
comes from. The fixture metrics carry only the fields every real metric has: a name, a display name, a
description and a unit. About 100 distractor metrics sit next to the 25 that cases expect, so a hit has to
beat close neighbors to land in the returned results.

A RELATED_WORD case shares no word stem with the name, display name or description of its expected
metric, so only meaning can find it. ``test_metric_search.py`` checks this mechanically.
"""

from enum import StrEnum

from posthog.dataclasses import frozen


class CaseType(StrEnum):
    EXACT_NAME = "exact_name"
    DISPLAY_NAME_WORDS = "display_name_words"
    DESCRIPTION_WORDS = "description_words"
    RELATED_WORD = "related_word"
    PARAPHRASED_QUESTION = "paraphrased_question"
    ACRONYM = "acronym"
    TYPO = "typo"
    WORD_FORM = "word_form"
    NEAR_SIBLING = "near_sibling"
    REAL_GAP = "real_gap"
    SEVERAL_PHRASINGS = "several_phrasings"


# The lexical lane must find these types on its own. The backend test holds it to that.
LEXICAL_CASE_TYPES = frozenset(
    {
        CaseType.EXACT_NAME,
        CaseType.DISPLAY_NAME_WORDS,
        CaseType.DESCRIPTION_WORDS,
        CaseType.ACRONYM,
        CaseType.TYPO,
        CaseType.WORD_FORM,
        CaseType.NEAR_SIBLING,
        CaseType.SEVERAL_PHRASINGS,
    }
)


@frozen
class FixtureMetric:
    name: str
    display_name: str
    description: str
    unit: str
    status: str
    hogql: str | None = None


@frozen
class SearchCase:
    name: str
    case_type: CaseType
    queries: tuple[str, ...]
    # Any of these in the returned hits counts as found. Empty for a real gap.
    expected: tuple[str, ...] = ()
    # For a near sibling: the metric the expected one must rank above.
    ranked_above: str | None = None


APPROVED = "approved"
PROPOSED = "proposed"

# The metrics the cases expect.
TARGET_METRICS: tuple[FixtureMetric, ...] = (
    FixtureMetric(
        name="mrr",
        display_name="MRR",
        description="Monthly recurring revenue from active paid subscriptions, in USD, at month end.",
        unit="usd",
        status=APPROVED,
    ),
    FixtureMetric(
        name="arr",
        display_name="ARR",
        description="Annual recurring revenue: month-end MRR times twelve.",
        unit="usd",
        status=APPROVED,
    ),
    FixtureMetric(
        name="net_new_mrr",
        display_name="Net new MRR",
        description="MRR added by new and expanding customers minus MRR lost to contraction and churn, per month.",
        unit="usd",
        status=APPROVED,
    ),
    FixtureMetric(
        name="weekly_active_users",
        display_name="Weekly active users",
        description="Distinct people who performed any tracked action in the last 7 days, internal users excluded.",
        unit="count",
        status=APPROVED,
    ),
    FixtureMetric(
        name="weekly_active_organizations",
        display_name="Weekly active organizations",
        description="Distinct customer organizations with at least one active member in the last 7 days.",
        unit="count",
        status=APPROVED,
    ),
    FixtureMetric(
        name="monthly_active_users",
        display_name="Monthly active users",
        description="Distinct people who performed any tracked action in the last 30 days, internal users excluded.",
        unit="count",
        status=APPROVED,
    ),
    FixtureMetric(
        name="daily_active_users",
        display_name="Daily active users",
        description="Distinct people who performed any tracked action on the day, internal users excluded.",
        unit="count",
        status=PROPOSED,
    ),
    FixtureMetric(
        name="logo_churn_rate",
        display_name="Logo churn rate",
        description="Share of paying customer organizations at the start of the month that cancelled by its end.",
        unit="percent",
        status=APPROVED,
    ),
    FixtureMetric(
        name="revenue_churn_rate",
        display_name="Revenue churn rate",
        description="Share of the MRR at the start of the month that cancellations and downgrades removed.",
        unit="percent",
        status=APPROVED,
    ),
    FixtureMetric(
        name="net_revenue_retention",
        display_name="Net revenue retention",
        description="Revenue this month from customers who paid twelve months ago, divided by their revenue then.",
        unit="percent",
        status=APPROVED,
    ),
    FixtureMetric(
        name="d30_retention_rate",
        display_name="Day 30 retention rate",
        description="Share of new signups who come back and perform a tracked action 30 days after signing up.",
        unit="percent",
        status=APPROVED,
    ),
    FixtureMetric(
        name="signup_to_paid_conversion",
        display_name="Signup to paid conversion",
        description="Share of new signups who start a paid plan within 30 days.",
        unit="percent",
        status=APPROVED,
    ),
    FixtureMetric(
        name="new_signups",
        display_name="New signups",
        description="Accounts created per day, test accounts excluded.",
        unit="count",
        status=PROPOSED,
    ),
    FixtureMetric(
        name="average_revenue_per_account",
        display_name="ARPA",
        description="MRR divided by the number of paying customer organizations.",
        unit="usd",
        status=APPROVED,
    ),
    FixtureMetric(
        name="customer_acquisition_cost",
        display_name="Customer acquisition cost",
        description="Sales and marketing spend in a month divided by the new paying customers in that month.",
        unit="usd",
        status=PROPOSED,
    ),
    FixtureMetric(
        name="support_tickets_opened",
        display_name="Support tickets opened",
        description="Support tickets customers opened per week, across email and chat.",
        unit="count",
        status=APPROVED,
    ),
    FixtureMetric(
        name="median_first_response_time",
        display_name="Median first response time",
        description="Median minutes from a support ticket opening to the first reply from staff.",
        unit="minutes",
        status=APPROVED,
    ),
    FixtureMetric(
        name="nps_score",
        display_name="NPS",
        description="Net promoter score from the in-app survey: percent promoters minus percent detractors.",
        unit="score",
        status=APPROVED,
    ),
    FixtureMetric(
        name="api_error_rate",
        display_name="API error rate",
        description="Share of public API requests that return a 5xx status, per hour.",
        unit="percent",
        status=APPROVED,
    ),
    FixtureMetric(
        name="p95_api_latency",
        display_name="API latency p95",
        description="95th percentile response time of public API requests, in milliseconds.",
        unit="ms",
        status=APPROVED,
    ),
    FixtureMetric(
        name="storage_used_gb",
        display_name="Storage used",
        description="Total file storage that customer organizations hold at the end of the day, in gigabytes.",
        unit="gb",
        status=PROPOSED,
    ),
    FixtureMetric(
        name="invoices_paid_amount",
        display_name="Invoices paid",
        description="Sum of the invoice amounts customers paid in the period, in USD, refunds excluded.",
        unit="usd",
        status=APPROVED,
        hogql="SELECT sum(amount) FROM stripe_invoices WHERE status = 'paid'",
    ),
    FixtureMetric(
        name="refund_amount",
        display_name="Refunds issued",
        description="Sum of the refunds issued to customers in the period, in USD.",
        unit="usd",
        status=PROPOSED,
    ),
    FixtureMetric(
        name="feature_adoption_rate",
        display_name="Feature adoption rate",
        description="Share of weekly active organizations that used a given feature at least once that week.",
        unit="percent",
        status=PROPOSED,
    ),
    FixtureMetric(
        name="trial_starts",
        display_name="Trial starts",
        description="Organizations that started a free trial of a paid plan, per week.",
        unit="count",
        status=APPROVED,
    ),
)


def _distractor(name: str, display_name: str, description: str, unit: str, status: str = PROPOSED) -> FixtureMetric:
    return FixtureMetric(name=name, display_name=display_name, description=description, unit=unit, status=status)


# Look-alike and unrelated metrics, so a correct hit has to win against close neighbors. None of them is a
# right answer to a case, and none holds a word of a real-gap query.
DISTRACTOR_METRICS: tuple[FixtureMetric, ...] = (
    # Revenue and billing.
    _distractor(
        "new_mrr", "New MRR", "MRR from customers whose first paid month is this month, in USD.", "usd", APPROVED
    ),
    _distractor(
        "expansion_mrr",
        "Expansion MRR",
        "MRR added by existing customers who added seats or moved to a larger plan, per month.",
        "usd",
        APPROVED,
    ),
    _distractor(
        "contraction_mrr",
        "Contraction MRR",
        "MRR lost when existing customers removed seats or moved to a smaller plan, per month.",
        "usd",
        APPROVED,
    ),
    _distractor("mrr_by_plan", "MRR by plan", "Month-end MRR split by pricing plan.", "usd"),
    _distractor(
        "mrr_growth_rate",
        "MRR growth rate",
        "Month-over-month change in month-end MRR, as a percent.",
        "percent",
        APPROVED,
    ),
    _distractor(
        "gross_revenue_retention",
        "Gross revenue retention",
        "Revenue kept from the customers of a year ago, counting downgrades and cancellations but not expansion.",
        "percent",
        APPROVED,
    ),
    _distractor("bookings", "Bookings", "Total contract value of the deals signed in the period, in USD.", "usd"),
    _distractor("billings", "Billings", "Amount invoiced in the period, before any payment arrives, in USD.", "usd"),
    _distractor("deferred_revenue", "Deferred revenue", "Invoiced amounts not yet earned at month end, in USD.", "usd"),
    _distractor(
        "one_time_revenue",
        "One-time revenue",
        "Revenue from setup fees and services that do not recur, per month.",
        "usd",
    ),
    _distractor(
        "average_contract_value",
        "Average contract value",
        "Mean first-year value of the annual contracts signed in the month.",
        "usd",
    ),
    _distractor(
        "customer_lifetime_value",
        "LTV",
        "Mean gross margin a paying organization brings before it cancels.",
        "usd",
        APPROVED,
    ),
    _distractor(
        "ltv_to_cac_ratio",
        "LTV to CAC ratio",
        "Customer lifetime value divided by the cost of winning the customer.",
        "ratio",
    ),
    _distractor(
        "cac_payback_months",
        "CAC payback",
        "Months of gross margin needed to earn back what it cost to win a customer.",
        "months",
    ),
    _distractor(
        "gross_margin",
        "Gross margin",
        "Revenue minus hosting and support costs, as a percent of revenue.",
        "percent",
        APPROVED,
    ),
    _distractor("hosting_cost", "Hosting cost", "Cloud infrastructure spend per month, in USD.", "usd"),
    _distractor(
        "discount_amount",
        "Discounts given",
        "Sum of the coupon and negotiated discounts applied to invoices, in USD.",
        "usd",
    ),
    _distractor(
        "failed_payments", "Failed payments", "Card charges that the payment provider declined, per week.", "count"
    ),
    _distractor(
        "dunning_recovery_rate",
        "Dunning recovery rate",
        "Share of declined card charges collected within 14 days.",
        "percent",
    ),
    _distractor(
        "overdue_invoices", "Overdue invoices", "Invoices still unpaid 30 days after their due date.", "count", APPROVED
    ),
    _distractor("average_revenue_per_user", "ARPU", "MRR divided by the number of paying users.", "usd", APPROVED),
    _distractor("annual_plan_share", "Annual plan share", "Share of paying organizations on a yearly plan.", "percent"),
    _distractor(
        "trial_to_paid_conversion",
        "Trial to paid conversion",
        "Share of trials that move to a paid plan before the trial ends.",
        "percent",
        APPROVED,
    ),
    _distractor(
        "quote_to_close_rate",
        "Quote to close rate",
        "Share of sales quotes that become signed contracts within 90 days.",
        "percent",
    ),
    _distractor(
        "pipeline_value",
        "Sales pipeline value",
        "Total value of the open sales opportunities at the end of the week, in USD.",
        "usd",
    ),
    _distractor(
        "sales_cycle_length",
        "Sales cycle length",
        "Median days from the first sales call to a signed contract.",
        "days",
    ),
    _distractor(
        "marketing_spend", "Marketing spend", "Paid ads, sponsorships and events spend per month, in USD.", "usd"
    ),
    _distractor(
        "cost_per_lead", "Cost per lead", "Marketing spend divided by the leads it brought in, per month.", "usd"
    ),
    _distractor(
        "tax_collected", "Sales tax collected", "Sales tax and VAT charged on invoices in the period, in USD.", "usd"
    ),
    _distractor(
        "credits_granted",
        "Credits granted",
        "Account credits given to customers as goodwill or promotions, in USD.",
        "usd",
    ),
    # Users and engagement.
    _distractor(
        "weekly_active_users_mobile",
        "Weekly active users (mobile)",
        "Distinct people active in the mobile app in the last 7 days.",
        "count",
        APPROVED,
    ),
    _distractor(
        "daily_active_organizations",
        "Daily active organizations",
        "Distinct customer organizations with an active member on the day.",
        "count",
    ),
    _distractor(
        "monthly_active_organizations",
        "Monthly active organizations",
        "Distinct customer organizations with an active member in the last 30 days.",
        "count",
        APPROVED,
    ),
    _distractor(
        "dau_mau_ratio",
        "DAU/MAU ratio",
        "Daily active users divided by monthly active users, as a percent.",
        "percent",
        APPROVED,
    ),
    _distractor(
        "weekly_api_usage", "Weekly API usage", "Calls made to the public API in the last 7 days.", "count", APPROVED
    ),
    _distractor("power_users", "Power users", "People active on at least 4 of the last 7 days.", "count"),
    _distractor("session_count", "Sessions", "Sessions started across web and mobile, per day.", "count"),
    _distractor(
        "average_session_duration", "Average session duration", "Mean length of a session, in minutes.", "minutes"
    ),
    _distractor("pageviews", "Pageviews", "Page loads on the marketing site and the app, per day.", "count"),
    _distractor("seats_used", "Seats used", "Paid seats assigned to a person, across all organizations.", "count"),
    _distractor("invites_sent", "Invites sent", "Team invitations sent by existing users, per week.", "count"),
    _distractor(
        "invite_acceptance_rate", "Invite acceptance rate", "Share of invitations accepted within 7 days.", "percent"
    ),
    _distractor(
        "activation_rate",
        "Activation rate",
        "Share of new signups who finish the setup checklist within 7 days.",
        "percent",
        APPROVED,
    ),
    _distractor(
        "time_to_activation",
        "Time to activation",
        "Median hours from signup to finishing the setup checklist.",
        "hours",
    ),
    _distractor(
        "onboarding_completion_rate",
        "Onboarding completion rate",
        "Share of new organizations that finish every onboarding step.",
        "percent",
    ),
    _distractor(
        "d7_retention_rate",
        "Day 7 retention",
        "Share of a signup cohort active again 7 days after signup.",
        "percent",
        APPROVED,
    ),
    _distractor(
        "d90_retention_rate",
        "Day 90 retention",
        "Share of a signup cohort active again 90 days after signup.",
        "percent",
    ),
    _distractor(
        "resurrected_users", "Resurrected users", "People active this week after at least 4 inactive weeks.", "count"
    ),
    _distractor(
        "dormant_organizations",
        "Dormant organizations",
        "Paying organizations with no active member for 30 days.",
        "count",
    ),
    _distractor(
        "customer_activation_count",
        "Customer activation count",
        "Organizations that reached their first key action this week.",
        "count",
        APPROVED,
    ),
    _distractor("dashboard_views", "Dashboard views", "Times a dashboard was opened, per day.", "count"),
    _distractor("reports_created", "Reports created", "Saved reports created by users, per week.", "count"),
    _distractor(
        "mobile_app_installs",
        "Mobile app installs",
        "First launches of the mobile app on a new device, per day.",
        "count",
    ),
    _distractor(
        "email_open_rate", "Email open rate", "Share of product emails opened within 3 days of sending.", "percent"
    ),
    _distractor(
        "push_opt_in_rate", "Push opt-in rate", "Share of mobile users who allow push notifications.", "percent"
    ),
    _distractor(
        "feature_requests", "Feature requests", "Ideas submitted on the public roadmap board, per month.", "count"
    ),
    _distractor(
        "referral_signups",
        "Referral signups",
        "New accounts that came from a customer referral link, per week.",
        "count",
    ),
    _distractor("waitlist_size", "Waitlist size", "People on the waitlist for features in private beta.", "count"),
    _distractor(
        "country_count",
        "Countries with users",
        "Distinct countries with at least one active user in the last 30 days.",
        "count",
    ),
    _distractor(
        "average_seats_per_organization",
        "Average seats per organization",
        "Paid seats divided by paying organizations.",
        "count",
    ),
    # Support and success.
    _distractor(
        "support_tickets_closed",
        "Support tickets closed",
        "Support tickets marked solved per week, across email and chat.",
        "count",
        APPROVED,
    ),
    _distractor(
        "median_time_to_resolution",
        "Median time to resolution",
        "Median hours from a ticket being opened to it being solved.",
        "hours",
        APPROVED,
    ),
    _distractor(
        "csat_score",
        "CSAT",
        "Share of support conversations rated good or great in the follow-up survey.",
        "percent",
        APPROVED,
    ),
    _distractor(
        "ticket_backlog", "Ticket backlog", "Open support tickets older than 2 days at the end of the day.", "count"
    ),
    _distractor("escalation_rate", "Escalation rate", "Share of support tickets passed to engineering.", "percent"),
    _distractor("chat_volume", "Chat volume", "Live chat conversations started per day.", "count"),
    _distractor("help_article_views", "Help article views", "Views of help center articles, per day.", "count"),
    _distractor(
        "onboarding_calls_booked",
        "Onboarding calls booked",
        "Calls booked with the customer success team, per week.",
        "count",
    ),
    _distractor(
        "health_score",
        "Account health score",
        "Weighted mix of usage, support load and payment status per paying organization.",
        "score",
    ),
    _distractor("renewal_rate", "Renewal rate", "Share of annual contracts that renew at their end date.", "percent"),
    # Engineering and infrastructure.
    _distractor("deploy_frequency", "Deploy frequency", "Production deploys per day.", "count"),
    _distractor(
        "change_failure_rate", "Change failure rate", "Share of deploys that need a rollback or a hotfix.", "percent"
    ),
    _distractor(
        "mean_time_to_recovery", "MTTR", "Mean minutes from an alert firing to the service working again.", "minutes"
    ),
    _distractor(
        "uptime", "Uptime", "Share of minutes in the month when the app answered health checks.", "percent", APPROVED
    ),
    _distractor(
        "page_load_time_p75",
        "Page load time p75",
        "75th percentile time for an app page to finish loading, in milliseconds.",
        "ms",
    ),
    _distractor(
        "javascript_exceptions", "Browser exceptions", "Uncaught browser exceptions per 1,000 pageviews.", "ratio"
    ),
    _distractor(
        "query_duration_p95",
        "Insight query duration p95",
        "95th percentile time to compute a saved insight, in seconds.",
        "seconds",
    ),
    _distractor(
        "events_ingested", "Events ingested", "Analytics events written to storage per day.", "count", APPROVED
    ),
    _distractor(
        "ingestion_lag_seconds",
        "Ingestion lag",
        "Seconds between an event arriving and it being queryable, at the 95th percentile.",
        "seconds",
    ),
    _distractor(
        "queue_depth", "Queue depth", "Jobs waiting in the background job queue at the top of the hour.", "count"
    ),
    _distractor(
        "cpu_utilization", "CPU utilization", "Mean CPU use across the application servers, as a percent.", "percent"
    ),
    _distractor("bandwidth_egress_gb", "Bandwidth out", "Data served from the CDN per day, in gigabytes.", "gb"),
    _distractor("build_duration", "Build duration", "Median minutes for the main branch build to finish.", "minutes"),
    _distractor("open_pull_requests", "Open pull requests", "Pull requests open at the end of the day.", "count"),
    _distractor(
        "security_vulnerabilities_open",
        "Open vulnerabilities",
        "Known security vulnerabilities not yet fixed.",
        "count",
    ),
    _distractor(
        "webhook_delivery_success_rate",
        "Webhook delivery success rate",
        "Share of outgoing webhooks that the receiver accepted on the first try.",
        "percent",
    ),
    _distractor("email_bounce_rate", "Email bounce rate", "Share of sent emails that bounced.", "percent"),
    _distractor("cache_hit_rate", "Cache hit rate", "Share of query results served from the cache.", "percent"),
    _distractor(
        "rate_limited_requests",
        "Rate-limited requests",
        "Public API requests rejected for going over the rate limit, per day.",
        "count",
    ),
    _distractor(
        "sdk_versions_outdated",
        "Outdated SDK share",
        "Share of events sent by an SDK more than two major versions old.",
        "percent",
    ),
    # Teams, content and other.
    _distractor("blog_visitors", "Blog visitors", "Distinct visitors to the company blog, per week.", "count"),
    _distractor(
        "newsletter_subscribers", "Newsletter subscribers", "People subscribed to the product newsletter.", "count"
    ),
    _distractor("community_posts", "Community posts", "Posts in the community forum, per week.", "count"),
    _distractor(
        "docs_search_queries", "Docs search queries", "Searches run on the documentation site, per day.", "count"
    ),
    _distractor(
        "partner_referrals", "Partner referrals", "Leads sent by agency and reseller partners, per month.", "count"
    ),
    _distractor(
        "event_attendance", "Event attendance", "People who attended a hosted webinar or meetup, per month.", "count"
    ),
    _distractor("hiring_pipeline", "Candidates in pipeline", "Job candidates in an active interview stage.", "count"),
    _distractor("office_cost", "Office cost", "Rent and facilities spend per month, in USD.", "usd"),
    _distractor(
        "carbon_footprint", "Carbon footprint", "Estimated tonnes of CO2 from cloud hosting per month.", "tonnes"
    ),
    # Created with a name and description only, as many metrics are.
    _distractor("legacy_revenue_v1", "", "Old revenue total kept for comparison with past board reports.", "usd"),
)

FIXTURE_METRICS: tuple[FixtureMetric, ...] = (*TARGET_METRICS, *DISTRACTOR_METRICS)


def _case(
    name: str,
    case_type: CaseType,
    *queries: str,
    expected: tuple[str, ...] = (),
    ranked_above: str | None = None,
) -> SearchCase:
    return SearchCase(name=name, case_type=case_type, queries=queries, expected=expected, ranked_above=ranked_above)


SEARCH_CASES: tuple[SearchCase, ...] = (
    # Exact name: the baseline every variant must keep.
    _case("exact_mrr", CaseType.EXACT_NAME, "mrr", expected=("mrr",)),
    _case("exact_nps", CaseType.EXACT_NAME, "NPS", expected=("nps_score",)),
    _case("exact_snake_name", CaseType.EXACT_NAME, "weekly_active_users", expected=("weekly_active_users",)),
    _case("exact_trial_starts", CaseType.EXACT_NAME, "trial starts", expected=("trial_starts",)),
    # Display name words.
    _case("display_net_new_mrr", CaseType.DISPLAY_NAME_WORDS, "net new MRR", expected=("net_new_mrr",)),
    _case("display_logo_churn", CaseType.DISPLAY_NAME_WORDS, "logo churn", expected=("logo_churn_rate",)),
    _case(
        "display_first_response",
        CaseType.DISPLAY_NAME_WORDS,
        "first response time",
        expected=("median_first_response_time",),
    ),
    _case(
        "display_day_30_retention", CaseType.DISPLAY_NAME_WORDS, "day 30 retention", expected=("d30_retention_rate",)
    ),
    _case(
        "display_support_tickets", CaseType.DISPLAY_NAME_WORDS, "support tickets", expected=("support_tickets_opened",)
    ),
    _case(
        "display_free_to_paid",
        CaseType.DISPLAY_NAME_WORDS,
        "free to paid conversion",
        expected=("signup_to_paid_conversion",),
    ),
    # Description words: the words are in the description, not the name.
    _case("description_subscription_revenue", CaseType.DESCRIPTION_WORDS, "subscription revenue", expected=("mrr",)),
    _case("description_customer_churn", CaseType.DESCRIPTION_WORDS, "customer churn", expected=("logo_churn_rate",)),
    _case(
        "description_first_reply",
        CaseType.DESCRIPTION_WORDS,
        "time to first reply",
        expected=("median_first_response_time",),
    ),
    _case("description_5xx_rate", CaseType.DESCRIPTION_WORDS, "5xx rate", expected=("api_error_rate",)),
    _case(
        "description_api_response_time", CaseType.DESCRIPTION_WORDS, "API response time", expected=("p95_api_latency",)
    ),
    _case("description_net_promoter", CaseType.DESCRIPTION_WORDS, "net promoter score", expected=("nps_score",)),
    # Related word: no stem of the query is in the name, display name or description of the expected metric.
    _case("related_subscriber_income", CaseType.RELATED_WORD, "subscriber income", expected=("mrr",)),
    _case("related_lost_clients", CaseType.RELATED_WORD, "lost clients", expected=("logo_churn_rate",)),
    _case(
        "related_agents_answer_quickly",
        CaseType.RELATED_WORD,
        "how quickly agents answer",
        expected=("median_first_response_time",),
    ),
    _case("related_backend_crashes", CaseType.RELATED_WORD, "backend crashes", expected=("api_error_rate",)),
    _case("related_endpoint_lag", CaseType.RELATED_WORD, "endpoint lag", expected=("p95_api_latency",)),
    _case(
        "related_capacity_consumed",
        CaseType.RELATED_WORD,
        "capacity consumed by uploads",
        expected=("storage_used_gb",),
    ),
    _case("related_loyalty_rating", CaseType.RELATED_WORD, "loyalty rating", expected=("nps_score",)),
    _case(
        "related_users_who_upgrade", CaseType.RELATED_WORD, "users who upgrade", expected=("signup_to_paid_conversion",)
    ),
    _case(
        "related_engaged_audience", CaseType.RELATED_WORD, "engaged audience size", expected=("weekly_active_users",)
    ),
    _case("related_money_returned", CaseType.RELATED_WORD, "money returned to buyers", expected=("refund_amount",)),
    _case("related_disk_usage", CaseType.RELATED_WORD, "disk usage", expected=("storage_used_gb",)),
    # Paraphrased question: the need asked as a question a person would type.
    _case(
        "question_monthly_subscription_revenue",
        CaseType.PARAPHRASED_QUESTION,
        "how much subscription revenue do we make per month",
        expected=("mrr",),
    ),
    _case(
        "question_signups_become_customers",
        CaseType.PARAPHRASED_QUESTION,
        "how many signups turn into paying customers",
        expected=("signup_to_paid_conversion",),
    ),
    _case(
        "question_customers_spend_more",
        CaseType.PARAPHRASED_QUESTION,
        "are existing customers spending more each year",
        expected=("net_revenue_retention",),
    ),
    _case(
        "question_users_stick_around",
        CaseType.PARAPHRASED_QUESTION,
        "do new users stick around a month later",
        expected=("d30_retention_rate",),
    ),
    _case(
        "question_recommend_us",
        CaseType.PARAPHRASED_QUESTION,
        "would customers recommend us to a friend",
        expected=("nps_score",),
    ),
    # Acronym.
    _case("acronym_wau", CaseType.ACRONYM, "wau", expected=("weekly_active_users",)),
    _case("acronym_mau", CaseType.ACRONYM, "MAU", expected=("monthly_active_users",)),
    _case("acronym_nrr", CaseType.ACRONYM, "nrr", expected=("net_revenue_retention",)),
    _case("acronym_cac", CaseType.ACRONYM, "cac", expected=("customer_acquisition_cost",)),
    _case("acronym_arpa", CaseType.ACRONYM, "arpa", expected=("average_revenue_per_account",)),
    # Typo.
    _case("typo_retension", CaseType.TYPO, "retension", expected=("d30_retention_rate", "net_revenue_retention")),
    _case("typo_chrun", CaseType.TYPO, "chrun rate", expected=("logo_churn_rate", "revenue_churn_rate")),
    _case("typo_lattency", CaseType.TYPO, "lattency", expected=("p95_api_latency",)),
    _case("typo_signpus", CaseType.TYPO, "signpus", expected=("new_signups",)),
    # Word form.
    _case("form_churned_customers", CaseType.WORD_FORM, "churned customers", expected=("logo_churn_rate",)),
    _case("form_refunded", CaseType.WORD_FORM, "refunds", expected=("refund_amount",)),
    _case("form_converting_signups", CaseType.WORD_FORM, "converting signups", expected=("signup_to_paid_conversion",)),
    _case("form_paid_invoices", CaseType.WORD_FORM, "paid invoice", expected=("invoices_paid_amount",)),
    _case("form_weekly_actives", CaseType.WORD_FORM, "weekly actives", expected=("weekly_active_users",)),
    # Near sibling: the right grain or slice must rank above its sibling.
    _case(
        "sibling_weekly_active_orgs",
        CaseType.NEAR_SIBLING,
        "weekly active orgs",
        expected=("weekly_active_organizations",),
        ranked_above="weekly_active_users",
    ),
    _case(
        "sibling_monthly_active_users",
        CaseType.NEAR_SIBLING,
        "monthly active users",
        expected=("monthly_active_users",),
        ranked_above="weekly_active_users",
    ),
    _case(
        "sibling_revenue_churn",
        CaseType.NEAR_SIBLING,
        "revenue churn",
        expected=("revenue_churn_rate",),
        ranked_above="logo_churn_rate",
    ),
    _case(
        "sibling_annual_recurring_revenue",
        CaseType.NEAR_SIBLING,
        "annual recurring revenue",
        expected=("arr",),
        ranked_above="mrr",
    ),
    _case(
        "sibling_daily_active_users",
        CaseType.NEAR_SIBLING,
        "daily active users",
        expected=("daily_active_users",),
        ranked_above="weekly_active_users",
    ),
    # Real gap: the catalog has no metric, so confident_match must be false.
    _case("gap_gateway_latency", CaseType.REAL_GAP, "gateway latency"),
    _case("gap_sandbox", CaseType.REAL_GAP, "sandbox"),
    _case("gap_flaky_tests", CaseType.REAL_GAP, "flaky tests"),
    _case("gap_employee_headcount", CaseType.REAL_GAP, "employee headcount"),
    _case("gap_warehouse_sync_failures", CaseType.REAL_GAP, "warehouse sync failures"),
    # No word survives normalization, so a metric with no display name must not match as a name.
    _case("gap_punctuation_only", CaseType.REAL_GAP, "???"),
    # A leading "-" is a search operator that would match every metric without the word.
    _case("gap_operator_only", CaseType.REAL_GAP, "-sandbox"),
    # Several phrasings of one need.
    _case("phrasings_mrr", CaseType.SEVERAL_PHRASINGS, "mrr", "monthly revenue", expected=("mrr",)),
    _case("phrasings_churn", CaseType.SEVERAL_PHRASINGS, "churn", "customers lost", expected=("logo_churn_rate",)),
    _case(
        "phrasings_response_time",
        CaseType.SEVERAL_PHRASINGS,
        "response time",
        "support speed",
        expected=("median_first_response_time",),
    ),
    _case("phrasings_nps", CaseType.SEVERAL_PHRASINGS, "nps", "survey score", expected=("nps_score",)),
)

FIXTURE_METRICS_BY_NAME = {metric.name: metric for metric in FIXTURE_METRICS}
