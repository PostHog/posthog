from typing import Optional
from uuid import uuid4

import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase
from braintrust_core import Score

from posthog.schema import AssistantMessage, EventTaxonomyItem, HumanMessage

from posthog.models.user import User
from posthog.sync import database_sync_to_async

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.graph.memory.prompts import (
    ENQUIRY_INITIAL_MESSAGE,
    SCRAPING_SUCCESS_KEY_PHRASE,
    SCRAPING_TERMINATION_MESSAGE,
)
from ee.hogai.graph.root.nodes import SLASH_COMMAND_INIT
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..base import MaxPublicEval


class MemoryLLMClassifier(LLMClassifier):
    def _run_eval_sync(self, output, expected, **kwargs):
        if not output:
            return Score(name=self._name(), score=None)
        if expected in [ENQUIRY_INITIAL_MESSAGE, SCRAPING_TERMINATION_MESSAGE]:
            # For the special cases, we MUST see the expected messages verbatim
            return Score(
                name=self._name(),
                score=1.0 if isinstance(output, AssistantMessage) and output.content == expected else 0.0,
            )
        return super()._run_eval_sync(output, expected, **kwargs)

    async def _run_eval_async(self, output, expected, **kwargs):
        if not output:
            return Score(name=self._name(), score=None)
        if expected in [ENQUIRY_INITIAL_MESSAGE, SCRAPING_TERMINATION_MESSAGE]:
            # For the special cases, we MUST see the expected messages verbatim
            return Score(
                name=self._name(),
                score=1.0 if isinstance(output, AssistantMessage) and output.content == expected else 0.0,
            )
        return await super()._run_eval_async(output, expected, **kwargs)


class SatisfiesProductDetails(MemoryLLMClassifier):
    """Binary check: Does the scraped content contain identifiable product features?"""

    def __init__(self, **kwargs):
        super().__init__(
            name="satisfies_product_details",
            prompt_template="""Determine if the scraped content contains identifiable product features.

A PASS requires:
- At least 2-3 specific product features are mentioned
- Features are described with actual names or functionality (not generic)
- Features relate to the actual product being analyzed

A FAIL means:
- No specific features mentioned, only vague descriptions
- Features are generic or unrelated to the actual product
- Content is purely marketing speak without concrete functionality

<input>{{input}}</input>
<expected_output>{{expected}}</expected_output>
<actual_output>{{output}}</actual_output>

Compare the output to the expected content. Does the output contain identifiable product features like those shown in the expected example? Be brutal.
- pass: Contains specific, identifiable product features
- fail: No identifiable product features found""",
            choice_scores={
                "pass": 1.0,
                "fail": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


class SatisfiesBusinessDetails(MemoryLLMClassifier):
    """Binary check: Does the scraped content contain business model information?"""

    def __init__(self, **kwargs):
        super().__init__(
            name="satisfies_business_details",
            prompt_template="""Determine if the scraped content contains business model information.

A PASS requires:
- Clear indication of how the company makes money (subscription, freemium, ads, etc.)
- OR specific pricing information mentioned
- OR monetization strategy described

A FAIL means:
- No mention of how the company generates revenue
- Only vague business descriptions without monetization details
- No pricing or business model information found

<input>{{input}}</input>
<expected_output>{{expected}}</expected_output>
<actual_output>{{output}}</actual_output>

Compare the output to the expected content. Does the output contain business model information like that shown in the expected example? Be brutal
- pass: Contains business model or monetization information
- fail: No business model information found""",
            choice_scores={
                "pass": 1.0,
                "fail": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


class SatisfiesTechnicalDetails(MemoryLLMClassifier):
    """Binary check: Does the scraped content contain technical implementation details?"""

    def __init__(self, **kwargs):
        super().__init__(
            name="has_technical_details",
            prompt_template="""Determine if the scraped content contains technical implementation details.

A PASS requires:
- Mention of specific technologies, frameworks, or platforms used
- OR API/integration capabilities described
- OR technical architecture or infrastructure details
- OR development/deployment information

A FAIL means:
- No technical details mentioned
- Only high-level product descriptions without technical specifics
- No mention of underlying technology or implementation

Note: Not all products will have technical details in their public materials, so this may legitimately fail.

<input>{{input}}</input>
<expected_output>{{expected}}</expected_output>
<actual_output>{{output}}</actual_output>

Compare the output to the expected content. Does the output contain technical implementation details like those shown in the expected example? Be brutal
- pass: Contains specific technical details
- fail: No technical details found""",
            choice_scores={
                "pass": 1.0,
                "fail": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


class HasCorrectStyle(MemoryLLMClassifier):
    """Binary check: Does the scraped content follow the required formatting structure?"""

    def __init__(self, **kwargs):
        super().__init__(
            name="has_correct_style",
            prompt_template=f"""Determine if the scraped content follows the required formatting structure.

A PASS requires ALL of the following:
- Starts with exactly "__{SCRAPING_SUCCESS_KEY_PHRASE} [some product/domain name]:__" (bold formatting with colon)
- Contains at least one section with #### heading format (h4 markdown headers)
- Sections should include relevant topics like "Product features", "User/Customer segments", "Business model", "Technical details", or "Brief history"
- Uses bullet points (-) or structured formatting within sections (not just paragraphs)
- Content is well-organized with clear separation between topics
- No follow-up suggestions or calls-to-action at the end
- No citation anywhere (i.e. link in parentheses)

A FAIL occurs if ANY of the following is true:
- Missing or incorrect opening format (doesn't start with "__{SCRAPING_SUCCESS_KEY_PHRASE} ...:__")
- No #### section headings found
- Poor organization with wall-of-text paragraphs instead of structured sections
- Contains follow-up suggestions like "Would you like to know more?" or "Contact us"
- Sections lack bullet points or clear structure
- Generic formatting without the specified markdown structure
- A citation link is found
- There is any follow-up suggestion for the reader (like "Let me know if you'd like X" or "To do something, go to Y")

Note: The format requirements are specifically defined in the memory initialization prompt and must be followed exactly.

<input>{{{{input}}}}</input>
<expected_output>{{{{expected}}}}</expected_output>
<actual_output>{{{{output}}}}</actual_output>

Compare the output to the expected content format. Does the output follow the exact required formatting structure with proper opening, #### headers, and bullet points like shown in the expected example? Be brutal
- pass: Follows all required formatting specifications exactly
- fail: Missing required formatting elements or includes prohibited content""",
            choice_scores={
                "pass": 1.0,
                "fail": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )


@pytest.fixture(scope="module")
def core_memory():
    """We override the conftest.py core_memory fixture, which has autouse=True, as for memory onboarding a CoreMemory must be ABSENT."""
    pass


@pytest.fixture
def call_memory_onboarding():
    """Fixture to call MemoryOnboardingNode with a parametrized EventTaxonomyItem as input."""

    async def callable(input: tuple[str, Optional[EventTaxonomyItem]]) -> Optional[AssistantMessage]:
        organization_name, taxonomy_item = input  # The org name MAY matter as it gets included in the system prompt
        # Because memory is stateful at the team level, each eval case here must have its own team instance
        _, team, user = await database_sync_to_async(User.objects.bootstrap)(
            organization_name=organization_name, email=f"{uuid4()}@example.com", password=None
        )
        conversation = await Conversation.objects.acreate(team=team, user=user)

        graph = (
            AssistantGraph(team=team, user=user)
            .add_memory_onboarding(AssistantNodeName.END)
            .compile(checkpointer=DjangoCheckpointer())
        )
        raw_state = await graph.ainvoke(
            AssistantState(messages=[HumanMessage(content=SLASH_COMMAND_INIT)]),
            # Mock the _retrieve_context method to return our input data via `configurable`
            # Because evals run concurrently and everything's async, patch() just doesn't work
            {"configurable": {"thread_id": conversation.id, "_mock_memory_onboarding_context": taxonomy_item}},
        )

        state = AssistantState.model_validate(raw_state)
        if not state.messages:
            return None
        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantMessage):
            return None
        return last_message

    return callable


@pytest.mark.django_db
async def eval_memory_onboarding(call_memory_onboarding, pytestconfig):
    await MaxPublicEval(
        experiment_name="memory_onboarding",
        task=call_memory_onboarding,
        scores=[
            SatisfiesProductDetails(),
            SatisfiesBusinessDetails(),
            SatisfiesTechnicalDetails(),
            HasCorrectStyle(),
        ],
        data=[
            # Case: SaaS, well-known and massive in scope (so this one is tricky to describe in any detail)
            EvalCase(
                input=(
                    "Salesforce",
                    EventTaxonomyItem(property="$host", sample_values=["salesforce.com"], sample_count=1),
                ),
                expected="""
__Here's what I found on salesforce.com:__

Salesforce is a leading cloud-based customer relationship management (CRM) platform and enterprise software company offering a broad suite of clouds and platform services (Sales Cloud, Service Cloud, Marketing Cloud, Commerce Cloud), plus analytics, integration, collaboration, data and AI capabilities (Tableau, MuleSoft, Slack, Data Cloud, Einstein / Agentforce) that are sold as modular, integrated SaaS products.

#### Product features
- Core CRM clouds: Sales Cloud (opportunity & pipeline management), Service Cloud (case & support management), Marketing Cloud (campaigns, personalization), Commerce Cloud (e‑commerce).
- Data & analytics: Tableau for analytics/BI and Data Cloud as a unified customer data layer (real‑time profiles, CDP-like capabilities, vector/unstructured support).
- Integration & extensibility: MuleSoft acquisitions and connectors (API-led integrations), AppExchange marketplace, platform tools (Flows, Apex, low-code/no-code builders) to build custom apps.
- AI and agents: Einstein AI and Agentforce (autonomous AI agents/assistant capabilities, Atlas reasoning engine, built-in guardrails and supervised deployment tools).
- Collaboration & ecosystem: Slack integration for in‑flow collaboration, plus partner ISV ecosystem, prebuilt industry templates and vertical solutions.

#### User / Customer segments
- Large enterprises and global organizations across industries (financial services, healthcare, retail, manufacturing, telecommunications) adopting full Customer 360 suites.
- Midsize businesses and SMBs via tiered CRM editions and Starter/Pro suites.
- System integrators, consultants, and ISVs that build and resell vertical solutions on the Salesforce Platform and AppExchange.

#### Business model
- Primarily subscription SaaS: per‑user/per‑month licensing with tiered editions and enterprise contracts (Starter/Pro/Enterprise/Unlimited and higher‑tier AI/agent offerings).
- Add‑ons and usage‑based credits: Data Cloud/Flex credits, premium AI/agent bundles (Agentforce/Eins­ten tiers), premium support, professional services and implementation.
- Ecosystem monetization: AppExchange marketplace, partner/reseller revenue, and professional services (consulting, implementation, managed services).

#### Technical details
- Multi‑product platform: Customer 360 architecture ties CRM apps to a central data layer (Data Cloud) and platform services (Flow automation, APIs, Apex) for real‑time activations and cross‑cloud workflows.
- Integration posture: Emphasis on API‑led connectivity (MuleSoft and connectors) to unify on‑prem, cloud, data warehouses and third‑party systems.
- AI & data stack: Native capabilities for RAG (retrieval‑augmented generation), vectorized unstructured data handling, governance/guardrails for enterprise AI, and tooling to build/manage autonomous agents.

#### Brief history
- Founded as a cloud CRM pioneer and public company in the early 2000s; growth strategy combined organic product development with major acquisitions to broaden capabilities. Major acquisitions include MuleSoft, Tableau and Slack (among others) to add integration, analytics and collaboration into the Salesforce portfolio.
""".strip(),
            ),
            # Case: SaaS, new
            EvalCase(
                input=(
                    "Artificial Societies",
                    EventTaxonomyItem(property="$host", sample_values=["app.societies.io"], sample_count=1),
                ),
                expected="""
__Here's what I found on societies.io (Artificial Societies):__

Artificial Societies (societies.io / app.societies.io) is a SaaS platform that builds AI-driven “artificial societies” (collections of AI personas and a social‑network model) so users can run rapid simulations to test content, messaging, product ideas and campaigns before launching them in the real world.

#### Product features
- Create Any Society: build target audiences in plain English or generate a personal society from your actual social media interactions.
- Rapid experiments: run multi-agent simulations in minutes to see reactions, spread, and engagement.
- Variant generation & automatic A/B testing: the product writes and tests multiple message variants (using your tone) alongside the original.
- Insights & forecasting: numeric scores, comments, summaries and a conversational intelligence ("Amos") for interpreting results.
- Persona & network modelling: a large persona database and social‑network graph used to model influence and information spread; simulations use many LLM calls and token budgets to represent individual and collective behavior.
- Contexts supported: social posts, emails, ads, headlines and other communication contexts.
(Primary source: product site).

#### User / customer segments
- Individual creators, founders and B2B marketers testing LinkedIn and other social content.
- Product and growth teams validating messaging, features and launches.
- PR, communications and content teams testing narratives and headlines.
- Agencies and market‑research buyers looking for faster/cheaper audience experiments.
- Enterprise customers requiring custom audiences, API and CRM/data integrations.
(Descriptions and customer examples from the site and launch pages).

#### Business model (pricing & monetization)
- Freemium + credits: a Free tier with starter simulation credits (three) to try the product.
- Pro subscription: listed at $55/month (monthly) or $40/month billed annually (site shows both monthly and annual pricing blocks). Pro unlocks unlimited societies and unlimited simulation credits.
- Enterprise: custom pricing for bespoke audience builds, API access, integrations and dedicated account management.
- Credits consumption: simulations and variant regenerations consume credits (Pro users have unlimited credits).
(Official pricing and FAQ on the site).

#### Technical details
- Primary domains / entry points: https://societies.io (marketing/docs) and https://app.societies.io (app / sign-up flow).
- API & integrations: enterprise offerings advertise API access and CRM/data integration capabilities.
- Underlying approach: persona creation from individual-level public data, social network graph construction, multi-agent LLM simulations (hundreds of LLM calls / millions of tokens per run are referenced).
- Product names / components referenced publicly: Reach (LinkedIn audience simulation), Amos (social intelligence engine).
(Information from the product site and related launch materials).

#### Brief history
- Founded in 2024 by James He and Patrick Sharpe; accepted to Y Combinator (W25 / Winter 2025).
- Early product launches included demos and "Reach" (simulating LinkedIn audiences); public launch activity appeared on Product Hunt in March 2025.
- Funding: reported combined pre‑seed and seed rounds (coverage cites roughly €4.5M / ~$5.3M total), with the seed led by Point72 Ventures and participation from Kindred Capital, Y Combinator and various angels / investors.
- Traction claims on the site and press: persona database size and platform usage metrics (persona database >1,000,000; thousands of users and many tens of thousands of simulations referenced on site and in press).
""".strip(),
            ),
            # Case: Mobile app, game
            EvalCase(
                input=(
                    "Supercell",
                    EventTaxonomyItem(
                        property="$app_namespace",
                        sample_values=["com.supercell.clashofclans"],
                        sample_count=1,
                    ),
                ),
                expected="""
__Here's what I found on Clash of Clans:__

Clash of Clans is a long-running, free-to-play mobile strategy game by Supercell where players build and upgrade a persistent village, train troops and Heroes, join/clash in Clans, and compete in multiplayer modes such as Clan Wars and seasonal competitive play.

#### Product features
- Core gameplay
  - Village/base building (resource collectors, defenses, walls) and asymmetric base design.
  - Attack phase where players assemble armies (troops, spells, siege machines) and deploy them against other players or single-player Goblin maps.
- Social & competitive systems
  - Clans (up to 50 members), Clan Wars, Clan War Leagues, Clan Games, and Clan Capital content for coordinated play.
  - Leaderboards, Legend League, friendly challenges, spectating and replays.
- Progression & meta features
  - Town Hall progression unlocking new troops/buildings; Heroes (Barbarian King, Archer Queen, Grand Warden, Royal Champion, etc.) and Hero skins.
  - Seasons and Battle Pass–style Gold Pass, special timed events, and periodic balance/feature updates.

#### User / Customer segments
- Mass market mobile players (casual to midcore) attracted to base-building and short-session competitive play.
- Social/competitive players who join clans, participate in Clan Wars and long-term progression.
- High-spending "whales" who purchase premium currency (gems), bundles and offers — a small share of users historically accounts for a large portion of revenue.

#### Business model
- Free-to-play with no mandatory ads; primary monetization via in-app purchases (gems, resource packs, Gold Pass, time-savers and timed offers). App Store listing shows multiple gem packs and Gold Pass options.
- Reliance on a small fraction of paying users (whales) plus recurring seasonal content and limited-time bundles to sustain high ARPU. Historical reporting places Clash of Clans among the highest-grossing mobile games with multi-billion cumulative revenue.

#### Technical details
- Primary bundle / package identifiers:
  - iOS App Store ID: id529479190 (App Store listing shows pricing, requirements, and in‑app products).
  - Android package name: com.supercell.clashofclans (widely referenced as the Play Store / APK package name).
- Official product pages / support paths:
  - Supercell official game page: /en/games/clashofclans on supercell.com.
  - App Store listing path: apps.apple.com/.../clash-of-clans/id529479190.
  - Official support / help pages linked from the app and Supercell site (in‑game Help & Support and help.supercellsupport.com).

#### Brief history
- Launched on iOS August 2, 2012; Android release followed in October 2013. Rapid adoption and recurring updates turned it into one of Supercell’s flagship, decade-plus live-service titles.
- Long-term commercial success: sustained high grossing rank across app stores and cumulative revenues in the multi‑billion-dollar range; Supercell’s cell-based studio model and focus on persistent titles supported ongoing development and seasonal content.
""".strip(),
            ),
            # Case: No domain/bundle ID available (e.g. only localhost was present in the data)
            EvalCase(
                input=("Zapier", None),  # No EventTaxonomyItem, but let's say the org name is well-known (Zapier)
                expected=ENQUIRY_INITIAL_MESSAGE,  # Should fall back to enquiry flow INSTEAD OF scraping
            ),
            # Case: Non-existing product
            EvalCase(
                input=(
                    "Rotundify",
                    EventTaxonomyItem(property="$host", sample_values=["rotundify.xyz"], sample_count=1),
                ),
                expected=SCRAPING_TERMINATION_MESSAGE,  # Should fall back to enquiry flow AFTER scraping
            ),
            # Case: Niche music app with multiple bundle IDs
            EvalCase(
                input=(
                    "Snare Music",
                    EventTaxonomyItem(
                        property="$app_namespace",
                        sample_values=["com.jackqcook.snare", "com.snaremusic.snare"],
                        sample_count=2,
                    ),
                ),
                expected="""
__Here's what I found on Snare (com.jackqcook.snare / com.snaremusic.snare):__

Snare (aka Snare Music) is a social music-discovery app that converts your listening habits into a feed, letting you follow others, react to their plays, post reviews, and engage over music.

#### Product features
- Connects with streaming platforms (Spotify / Apple Music) to import recent listening history.
- Live social feed: shows what friends are currently listening to (or recently listened) in a feed format.
- Reaction / engagement tools: users can react (likes, comments) to others' plays.
- Reviews / commentary: ability to write reviews on albums/tracks within the app.
- Discovery / recommendation features: suggestions (called “Snare Samples” or algorithmic picks) based on user activity.
- Social graph: following system (you follow friends / users) to tailor the feed.
- Basic version is free; updates indicate bug fixes, UI tweaks, algorithm improvements (e.g. “better algorithm for Snare Samples”)

#### User / customer segments
- Music enthusiasts who like to see what peers are listening to and discuss music.
- Early adopters of social / discovery tools in the music space.
- Playlist curators, tastemakers, influencers who want social reach or community feedback.
- Users dissatisfied with “cold” algorithmic recommendations and seeking more human-curated or socially filtered discovery.

#### Business model
- No public disclosures of paid features or pricing (as of available data).
- Likely freemium: core features free, with potential premium tier for enhanced discovery / analytics / filtering / no ads (though not confirmed).
- Monetization might include sponsorships, affiliate revenue (for streaming referrals), or future paid features for power users.
- No clear revenue metrics or public funding data found.

#### Technical details
- Website: snaremusic.app — “Discover, rate, and share your favorite albums. Connect with friends … join conversations about the tracks that move you.”
- App version history: latest version 1.1.0 for iOS at least; update notes mention bug fixes, minor improvements.
- Key flows / URL paths likely include:
- /login / connect (to Spotify / Apple Music)
  - /feed (social feed of plays)
  - /profile / settings
  - /review / comment pages
  - /discover / algorithmic suggestions
- Mobile first (iOS, possibly Android expectation in future).
- The app appears “new” / early stage (version numbering low, frequent iterative changes).

Brief history
- Developer / “Quentin Cook” is listed in app metadata.
- First public version around August 2025 (v1.0 in August).
- Update cycle is active (versions 1.0 → 1.0.6 → 1.1.0) with feature tweaks like better algorithms, UI changes.
- The domain / branding is “Snare — the app for music discovery.
""".strip(),
            ),
        ],
        pytestconfig=pytestconfig,
    )
