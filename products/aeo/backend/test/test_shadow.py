from unittest.mock import patch

from products.aeo.backend import shadow
from products.aeo.backend.competitors import BrandInput, ClaudeConfirmation
from products.aeo.backend.test.fake_decisions import FakeDecisionModel

RUN = shadow.ShadowRun(
    team_id=1,
    trace_id="5d9c3a1e-2b4f-4c6d-8e7f-0a1b2c3d4e5f",
    site={"site": "example.com", "brand": "Example", "description": "unknown"},
    brands=(BrandInput(name="Lantern", domain="lantern.example.org"), BrandInput(name="Dev", domain="dev.to")),
    live_model=shadow.LIVE_HEURISTIC,
    live_decisions={"lantern.example.org": True, "dev.to": True},
)


def test_shadow_captures_one_generation_per_model_with_the_decision_per_brand() -> None:
    jev = FakeDecisionModel(lambda text: 0.9 if text.startswith("Lantern") else 0.2)
    claude = ClaudeConfirmation(
        model="claude-sonnet-5",
        decisions={"lantern.example.org": True, "dev.to": False},
        input_tokens=500,
        output_tokens=40,
        cost_usd=0.0014,
    )
    with (
        patch("products.aeo.backend.decisions.build_system_one_client", return_value=jev),
        patch("products.aeo.backend.competitors.confirm_competitors_with_claude", return_value=claude),
        patch("products.aeo.backend.shadow.capture_ai_internal_for_team") as capture,
    ):
        shadow.run_shadow(RUN)

    events = [call.kwargs for call in capture.call_args_list]
    assert [(e["event_name"], e["properties"]["aeo_role"], e["properties"]["$ai_model"]) for e in events] == [
        ("$ai_generation", "live", "heuristic"),
        ("$ai_generation", "shadow", "posthog/hogference/jeeves-0.1"),
        ("$ai_generation", "shadow", "claude-sonnet-5"),
    ]
    assert {e["properties"]["$ai_trace_id"] for e in events} == {RUN.trace_id}
    assert [e["properties"]["aeo_decisions"] for e in events] == [
        {"lantern.example.org": True, "dev.to": True},
        {"lantern.example.org": True, "dev.to": False},
        {"lantern.example.org": True, "dev.to": False},
    ]
    assert events[2]["properties"]["$ai_total_cost_usd"] == 0.0014
    assert events[1]["properties"]["$ai_output_choices"][0]["content"][1] == {
        "domain": "dev.to",
        "competitor": False,
        "p": 0.2,
    }
