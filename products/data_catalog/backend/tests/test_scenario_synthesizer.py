from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from parameterized import parameterized

from products.data_catalog.evals import scenario_synthesizer as pack


@parameterized.expand(
    [
        ("wau_spike", pack.build_wau_spike),
        ("wau_bot_spike", pack.build_wau_bot_spike),
        ("share_drop_flag", pack.build_share_drop_flag),
        ("share_dau", pack.build_share_dau),
        ("mcp_tool_shipped", pack.build_mcp_tool_shipped),
        ("mcp_tool_failures", pack.build_mcp_tool_failures),
        ("revenue_rep_outlier", pack.build_revenue_rep_outlier),
        ("slack_export", pack.build_slack_export),
        ("renewal_account", pack.build_renewal_account),
        ("expansion_account", pack.build_expansion_account),
        ("upgrade_banner", pack.build_upgrade_banner),
    ]
)
def test_needles_are_deterministic(_name: str, build: Callable[[], object]) -> None:
    assert build() == build()


def test_planted_people_carry_the_pack_token_and_a_reserved_domain() -> None:
    persons = (
        pack.build_wau_spike().persons
        + pack.build_wau_bot_spike().persons
        + pack.build_share_drop_flag().events.persons
        + pack.build_mcp_tool_shipped().persons
        + pack.build_mcp_tool_failures().persons
        + pack.build_share_dau().persons
        + pack.build_renewal_account().members.persons
        + pack.build_expansion_account().members.persons
        + pack.build_upgrade_banner().events.persons
    )
    assert all(pack.PACK_TOKEN in person.distinct_id for person in persons)
    assert all(person.email.endswith(f"@{pack.PACK_EMAIL_DOMAIN}") for person in persons if person.email)
    assert all(pack.PACK_TOKEN in deal.rep_email for deal in pack.build_revenue_rep_outlier().deals)


def test_wau_spikes_stay_inside_their_window() -> None:
    campaign = pack.build_wau_spike()
    landings = [event for event in campaign.events if event.properties.get("utm_source") == pack.CAMPAIGN_UTM_SOURCE]
    assert {event.days_ago for event in landings} == set(pack.WAU_SPIKE_DAYS_AGO)
    assert len({event.distinct_id for event in landings}) == pack.WAU_SPIKE_PERSON_COUNT
    assert min(event.days_ago for event in campaign.events) >= pack.WAU_SPIKE_LAST_RETURN_DAYS_AGO
    # Campaign users without the web SDK properties read as scripted accounts, not as campaign traffic.
    assert all(event.properties["$lib"] == "web" for event in campaign.events)
    initial = pack.initial_person_properties(campaign.events)
    assert len(initial) == pack.WAU_SPIKE_PERSON_COUNT
    for properties in initial.values():
        assert properties["$initial_utm_source"] == pack.CAMPAIGN_UTM_SOURCE
        assert properties["$initial_pathname"] == pack.CAMPAIGN_PATH
        assert properties["$initial_referring_domain"] == pack.CAMPAIGN_REFERRING_DOMAIN

    bots = pack.build_wau_bot_spike()
    assert {event.days_ago for event in bots.events} <= set(pack.WAU_SPIKE_DAYS_AGO)
    assert len({event.distinct_id for event in bots.events}) == pack.WAU_BOT_DISTINCT_ID_COUNT
    assert {event.event for event in bots.events} == {"$pageview"}
    assert {event.properties["$browser"] for event in bots.events} == {pack.WAU_BOT_BROWSER}


def test_flat_wau_holds_weekly_actives_level_on_a_growing_base() -> None:
    days = 100
    daily_active: list[set[str]] = [
        {f"user-{index}" for index in range(1_100 - 9 * day) if (index + day) % 3 == 0} for day in range(days)
    ]
    needle = pack.build_flat_wau(daily_active, latest_minute=600)
    for event in needle.events:
        daily_active[event.days_ago].add(event.distinct_id)
    weekly = pack.rolling_weekly_actives(daily_active)
    # The first week of data has windows that reach past its start, so only full windows count.
    changes = [abs(weekly[day] / weekly[day + 7] - 1) for day in range(days - 14)]
    assert max(changes) <= 0.02
    assert all(event.minute_of_day < 600 for event in needle.events if event.days_ago == 0)


def test_share_dau_has_the_same_sharers_every_day() -> None:
    sharers_by_day = Counter(event.days_ago for event in pack.build_share_dau().events)
    assert sharers_by_day == dict.fromkeys(range(1, pack.SHARE_DAU_WINDOW_DAYS + 1), pack.SHARE_DAU_DAILY_SHARERS)


def test_share_drop_flag_stops_only_the_blocked_cohort() -> None:
    needle = pack.build_share_drop_flag()
    exposures = {
        event.distinct_id: event.properties["$feature_flag_response"]
        for event in needle.events.events
        if event.event == "$feature_flag_called"
    }
    window = range(pack.SHARE_EXPOSURE_TO_DAYS_AGO, pack.SHARE_BLOCK_FROM_DAYS_AGO + 1)
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
    assert amounts[0] == round(pack.CRM_OUTLIER_FACTOR * amounts[1], 2)
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


def test_mcp_failing_tool_fails_more_in_the_last_week_and_other_tools_never_fail() -> None:
    events = pack.build_mcp_tool_failures().events
    failing = [event for event in events if event.properties["tool_name"] == pack.MCP_FAILING_TOOL]

    def failure_share(recent: bool) -> float:
        calls = [event for event in failing if (event.days_ago <= pack.MCP_FAILURE_RISE_DAYS) == recent]
        return sum(event.properties["$mcp_is_error"] for event in calls) / len(calls)

    assert round(failure_share(recent=False), 2) == 0.05
    assert round(failure_share(recent=True), 2) == 0.33
    assert not any(
        event.properties["$mcp_is_error"] for event in events if event.properties["tool_name"] != pack.MCP_FAILING_TOOL
    )


def test_slack_export_holds_one_pretax_note() -> None:
    texts = [row[3] for row in pack.build_slack_export().table.rows]
    assert texts.count(pack.SLACK_PRETAX_TEXT) == 1
    assert sum("pre-tax" in text for text in texts) == 1


@parameterized.expand(
    [
        ("first_day", 20, 20, 0.0),
        ("last_day", 20, 1, 0.25),
        ("midway", 21, 11, 0.125),
        # A one-day window has no growth to spread, so it starts at the end share.
        ("one_day_window", 1, 1, 0.25),
    ]
)
def test_adoption_share_grows_linearly_to_the_end_share(
    _name: str, first_seen_days_ago: int, days_ago: int, expected_share: float
) -> None:
    spec = pack.AdoptionSpec(
        event="previewed_file", first_seen_days_ago=first_seen_days_ago, start_share=0.0, end_share=0.25
    )
    assert spec.share_on(days_ago) == expected_share


def _bills(needle: pack.AccountNeedle) -> list[float]:
    bills = sorted((event for event in needle.members.events if event.event == "paid_bill"), key=lambda e: -e.days_ago)
    return [event.properties["amount_usd"] for event in bills]


def test_renewal_account_loses_members_and_most_of_its_bill() -> None:
    needle = pack.build_renewal_account()
    assert _bills(needle) == [200.0, 200.0, 180.0, 60.0]
    assert needle.account.properties["team_size"] == pack.RENEWAL_START_MEMBERS - len(pack.RENEWAL_REMOVAL_DAYS_AGO)
    assert {event.properties["$group_0"] for event in needle.members.events} == {needle.account.group_key}
    removed = dict(zip(reversed(needle.members.persons), pack.RENEWAL_REMOVAL_DAYS_AGO))
    for person, removal_day in removed.items():
        member_days = [event.days_ago for event in needle.members.events if event.distinct_id == person.distinct_id]
        assert min(member_days) > removal_day
    downgrades = [event for event in needle.members.events if event.event == "downgraded_plan"]
    assert [(event.days_ago, event.properties["new_plan"]) for event in downgrades] == [
        (pack.RENEWAL_DOWNGRADE_DAYS_AGO, pack.BUSINESS_STANDARD_PLAN)
    ]


def test_expansion_account_doubles_its_bill_while_invited_members_stay_idle() -> None:
    needle = pack.build_expansion_account()
    assert _bills(needle) == [50.0, 60.0, 100.0]
    core = {person.distinct_id for person in needle.members.persons[: pack.EXPANSION_CORE_MEMBERS]}
    file_actors = {
        event.distinct_id
        for event in needle.members.events
        if event.event in ("uploaded_file", "downloaded_file", "shared_file_link")
    }
    assert file_actors == core
    for person, invite_day in zip(
        needle.members.persons[pack.EXPANSION_CORE_MEMBERS :], pack.EXPANSION_INVITE_DAYS_AGO
    ):
        assert {event.days_ago for event in needle.members.events if event.distinct_id == person.distinct_id} == {
            invite_day
        }


def test_upgrade_banner_doubles_upgrades_and_most_extra_upgraders_downgrade_within_a_week() -> None:
    needle = pack.build_upgrade_banner()
    events = needle.events.events
    exposed_on = {
        event.distinct_id: (event.properties["$feature_flag_response"], event.days_ago)
        for event in events
        if event.event == "$feature_flag_called"
    }
    upgraded_on = {event.distinct_id: event.days_ago for event in events if event.event == "upgraded_plan"}
    downgraded_on = {event.distinct_id: event.days_ago for event in events if event.event == "downgraded_plan"}
    assert min(event.days_ago for event in events) >= 1
    assert all(day < pack.UPGRADE_BANNER_START_DAYS_AGO for _, day in exposed_on.values())
    for arm in pack.UPGRADE_BANNER_ARMS:
        arm_ids = {distinct_id for distinct_id, (variant, _) in exposed_on.items() if variant == arm.variant}
        assert len(arm_ids) == pack.UPGRADE_BANNER_PERSONS_PER_VARIANT
        assert len(arm_ids & upgraded_on.keys()) == arm.upgraders
        assert len(arm_ids & downgraded_on.keys()) == arm.downgraders
    for distinct_id, upgrade_day in upgraded_on.items():
        assert upgrade_day <= exposed_on[distinct_id][1]
    for distinct_id, downgrade_day in downgraded_on.items():
        assert 0 < upgraded_on[distinct_id] - downgrade_day < pack.UPGRADE_BANNER_DOWNGRADE_WITHIN_DAYS


def test_preview_launch_fails_a_quarter_of_one_file_type_and_no_other() -> None:
    spec = pack.PREVIEW_LAUNCH
    previews = [(f"user-{index}", day) for index in range(500) for day in range(1, 21)]
    failing = Counter(spec.file_type_for(user, day) for user, day in previews if spec.fails(user, day))
    of_type = Counter(spec.file_type_for(user, day) for user, day in previews)
    assert set(failing) == {spec.failing_file_type}
    assert abs(failing[spec.failing_file_type] / of_type[spec.failing_file_type] - spec.failure_share) < 0.03
