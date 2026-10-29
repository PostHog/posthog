from __future__ import annotations

from collections import Counter

from parameterized import parameterized

from products.data_catalog.evals import scenario_synthesizer as pack


@parameterized.expand(
    [
        ("wau_spike", pack.build_wau_spike),
        ("wau_bot_spike", pack.build_wau_bot_spike),
        ("share_drop_flag", pack.build_share_drop_flag),
        ("mcp_tool_shipped", pack.build_mcp_tool_shipped),
        ("revenue_rep_outlier", pack.build_revenue_rep_outlier),
        ("slack_export", pack.build_slack_export),
        ("account_health", pack.build_account_health),
    ]
)
def test_needles_are_deterministic(_name: str, build) -> None:
    assert build() == build()


def test_planted_people_carry_the_pack_token_and_a_reserved_domain() -> None:
    persons = (
        pack.build_wau_spike().persons
        + pack.build_wau_bot_spike().persons
        + pack.build_share_drop_flag().events.persons
        + pack.build_mcp_tool_shipped().persons
    )
    assert all(pack.PACK_TOKEN in person.distinct_id for person in persons)
    assert all(person.email.endswith(f"@{pack.PACK_EMAIL_DOMAIN}") for person in persons if person.email)
    assert all(pack.PACK_TOKEN in deal.rep_email for deal in pack.build_revenue_rep_outlier().deals)


def test_wau_spikes_stay_inside_their_window() -> None:
    campaign = pack.build_wau_spike()
    signups = {event.distinct_id for event in campaign.events if event.event == "signed_up"}
    assert len(signups) == pack.WAU_SPIKE_PERSON_COUNT
    assert {event.days_ago for event in campaign.events} == set(pack.WAU_SPIKE_DAYS_AGO)

    bots = pack.build_wau_bot_spike()
    assert {event.days_ago for event in bots.events} <= set(pack.WAU_SPIKE_DAYS_AGO)
    assert len({event.distinct_id for event in bots.events}) == pack.WAU_BOT_DISTINCT_ID_COUNT
    assert {event.event for event in bots.events} == {"$pageview"}
    assert {event.properties["$browser"] for event in bots.events} == {pack.WAU_BOT_BROWSER}


def test_share_drop_flag_stops_only_the_blocked_cohort() -> None:
    needle = pack.build_share_drop_flag()
    exposures = {
        event.distinct_id: event.properties["$feature_flag_response"]
        for event in needle.events.events
        if event.event == "$feature_flag_called"
    }
    window = range(pack.SHARE_BLOCK_TO_DAYS_AGO, pack.SHARE_BLOCK_FROM_DAYS_AGO + 1)
    shares_in_window = Counter(
        exposures[event.distinct_id]
        for event in needle.events.events
        if event.event == pack.SHARE_EVENT and event.days_ago in window
    )
    shares_before = Counter(
        exposures[event.distinct_id]
        for event in needle.events.events
        if event.event == pack.SHARE_EVENT and event.days_ago > pack.SHARE_BLOCK_FROM_DAYS_AGO
    )
    assert shares_in_window[pack.SHARE_FLAG_BLOCKED_VARIANT] == 0
    assert shares_before[pack.SHARE_FLAG_BLOCKED_VARIANT] > 0
    assert shares_in_window[pack.SHARE_FLAG_CONTROL_VARIANT] > 0
    # The blocked cohort must dominate the baseline, or the total would not visibly drop.
    assert shares_before[pack.SHARE_FLAG_BLOCKED_VARIANT] > 4 * shares_before[pack.SHARE_FLAG_CONTROL_VARIANT]


def test_revenue_outlier_and_its_duplicate_decide_the_ranking() -> None:
    outlier = pack.build_revenue_rep_outlier()
    amounts = sorted({deal.amount_usd for deal in outlier.deals}, reverse=True)
    assert amounts[0] >= pack.CRM_OUTLIER_FACTOR * amounts[1] * 0.99
    assert Counter(deal.deal_id for deal in outlier.deals)[outlier.outlier_deal_id] == 2
    assert outlier.top_reps_with_outlier[0] == pack.CRM_OUTLIER_REP_NAME
    assert pack.CRM_OUTLIER_REP_NAME not in outlier.top_reps_without_outlier


def test_mcp_export_tool_ships_mid_window_and_correlates_with_share() -> None:
    events = pack.build_mcp_tool_shipped().events
    export_days = [event.days_ago for event in events if event.properties["tool_name"] == pack.MCP_EXPORT_TOOL]
    assert max(export_days) == pack.MCP_EXPORT_FIRST_SEEN_DAYS_AGO

    sessions: dict[str, Counter[str]] = {}
    for event in events:
        sessions.setdefault(event.properties["$session_id"], Counter())[event.properties["tool_name"]] += 1
    with_export = [tools[pack.MCP_SHARE_TOOL] for tools in sessions.values() if tools[pack.MCP_EXPORT_TOOL]]
    without_export = [tools[pack.MCP_SHARE_TOOL] for tools in sessions.values() if not tools[pack.MCP_EXPORT_TOOL]]
    assert sum(with_export) / len(with_export) == 3 * sum(without_export) / len(without_export)


def test_slack_and_health_tables_match_their_declared_truths() -> None:
    slack = pack.build_slack_export()
    texts = [row[3] for row in slack.table.rows]
    assert texts.count(pack.SLACK_PRETAX_TEXT) == 1
    assert sum("pre-tax" in text for text in texts) == 1

    unhappy_counts = Counter(
        account
        for _, days_ago, _, text in slack.table.rows
        if "unhappy" in text and days_ago <= pack.SLACK_UNHAPPY_WINDOW_DAYS
        for account in pack._ACCOUNT_NAMES
        if text.startswith(account) or f"with {account}" in text
    )
    flagged = {account for account, count in unhappy_counts.items() if count >= pack.SLACK_UNHAPPY_THRESHOLD}
    assert flagged == set(slack.unhappy_accounts)

    health = pack.build_account_health()
    at_risk = {row[0] for row in health.table.rows if row[1] > pack.CHURN_HEALTH_THRESHOLD}
    assert at_risk == set(health.at_risk_accounts)
    # The two branches overlap, so a union and a sum of the two lists give different answers.
    assert at_risk & flagged
