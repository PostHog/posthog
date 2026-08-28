# Product empty state adoption

Tracks which product scenes show the shared setup empty state and which still show something older.
It is a work queue, not a design document.

- What the platform is and how to adopt it: [`frontend/src/lib/components/ProductEmptyState/README.md`](../../frontend/src/lib/components/ProductEmptyState/README.md)
- Step-by-step for one product: the `building-product-empty-states` skill
- Reference adoption: `products/mcp_analytics/frontend/emptyState/`

A scene has adopted the platform when its `SceneExport` declares `emptyState`.
Everything else is either a hand-rolled empty state, the deprecated `ProductIntroduction`, or nothing at all.

## Regenerating the lists

These lists are a snapshot and go stale. Both queries below reproduce them.

Adopted scenes:

```bash
git grep -nE '^\s+emptyState: ' -- 'frontend/src' 'products/'
```

Scenes still on the deprecated component:

```bash
git grep -ln 'ProductIntroduction' -- 'frontend/src' 'products/'
```

Filter both by hand: `emptyState:` is also an unrelated prop on `LemonTable`, `Playlist`, and
`TaxonomicFilter`, and some `ProductIntroduction` hits are the component itself, dashboard widget
tiles, or `FeaturePreviewSceneGate` rather than scene empty states.

## Adopted

Rows marked "in review" are not on `master` yet. See "Regenerating the lists" for a live count.

| Product                | Scene                                                                               | Status                |
| ---------------------- | ----------------------------------------------------------------------------------- | --------------------- |
| MCP analytics          | `products/mcp_analytics/frontend/MCPAnalyticsScene.tsx`                             | on master (reference) |
| LLM analytics          | `products/ai_observability/frontend/AIObservabilityScene.tsx`                       | on master             |
| LLM prompts            | `products/ai_observability/frontend/prompts/LLMPromptsScene.tsx`                    | on master             |
| Support                | `products/conversations/frontend/scenes/tickets/SupportTicketsScene.tsx`            | on master             |
| Early access features  | `products/early_access_features/frontend/EarlyAccessFeatures.tsx`                   | on master             |
| Endpoints              | `products/endpoints/frontend/EndpointsScene.tsx`                                    | on master             |
| Experiments            | `products/experiments/frontend/scenes/ExperimentsScene.tsx`                         | on master             |
| Feature flags          | `frontend/src/scenes/feature-flags/FeatureFlags.tsx`                                | on master             |
| Links                  | `products/links/frontend/LinksScene.tsx`                                            | on master             |
| Product tours          | `frontend/src/scenes/product-tours/ProductTours.tsx`                                | on master             |
| Replay vision          | `products/replay_vision/frontend/replay_scanners/ReplayScannersScene.tsx`           | on master             |
| Skills                 | `products/skills/frontend/LLMSkillsScene.tsx`                                       | on master             |
| User interviews        | `products/user_interviews/frontend/UserInterviews.tsx`                              | on master             |
| Web scripts            | `frontend/src/scenes/data-pipelines/WebScriptsScene.tsx`                            | on master             |
| Error tracking         | `products/error_tracking/frontend/scenes/ErrorTrackingScene/ErrorTrackingScene.tsx` | on master             |
| Logs                   | `products/logs/frontend/LogsScene.tsx`                                              | on master             |
| Tracing                | `products/tracing/frontend/TracingScene.tsx`                                        | on master             |
| Metrics                | `products/metrics/frontend/MetricsScene.tsx`                                        | on master             |
| Surveys                | `frontend/src/scenes/surveys/Surveys.tsx`                                           | on master             |
| Session replay         | `frontend/src/scenes/session-recordings/SessionRecordings.tsx`                      | on master             |
| Web vitals             | `frontend/src/scenes/web-analytics/WebAnalyticsScene.tsx`                           | on master             |
| Data warehouse sources | `products/data_warehouse/frontend/scenes/SourcesScene/SourcesScene.tsx`             | on master             |
| Workflows              | `products/workflows/frontend/WorkflowsScene.tsx`                                    | on master             |
| Marketing analytics    | `frontend/src/scenes/marketing-analytics/MarketingAnalyticsScene.tsx`               | on master             |
| Customer analytics     | `products/customer_analytics/frontend/CustomerAnalyticsScene.tsx`                   | in review             |
| Actions                | `products/actions/frontend/pages/Actions.tsx`                                       | on master             |
| Annotations            | `frontend/src/scenes/annotations/Annotations.tsx`                                   | on master             |
| Cohorts                | `frontend/src/scenes/cohorts/Cohorts.tsx`                                           | on master             |
| Dashboards             | `frontend/src/scenes/dashboard/dashboards/Dashboards.tsx`                           | on master             |
| Product analytics      | `frontend/src/scenes/saved-insights/SavedInsights.tsx`                              | on master             |

Only four products resolve their status at app boot, via a `setupProbe` in their manifest:
LLM analytics, error tracking, MCP analytics, web analytics.
Every other adopter pays a scene-level spinner on each entry, including each trip back from a
detail page. Event-data products (logs, tracing, metrics, session replay) qualify for a probe and
do not have one yet.

## Not adopted

### Tier 1: highest-traffic first-run surfaces

These are the scenes a new user is most likely to land on before they have data.

| Product                | Scene                                                       | Shows instead         |
| ---------------------- | ----------------------------------------------------------- | --------------------- |
| Single empty dashboard | `frontend/src/scenes/dashboard/EmptyDashboardComponent.tsx` | `ProductIntroduction` |

### Tier 2: cheap, or actively misleading today

| Product                  | Scene                                                                       | Shows instead                                                                                                                                                                                                                    |
| ------------------------ | --------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Web analytics (main tab) | `frontend/src/scenes/web-analytics/WebAnalyticsDashboard.tsx`               | `ProductIntroduction` behind `WEB_ANALYTICS_EMPTY_ONBOARDING`, with a button that redirects into `urls.onboarding()`. The scene already wires the gate for web vitals, so this needs a second config scoped with `scenes: [...]` |
| Signals inbox            | `products/signals/frontend/inbox/InboxScene.tsx`                            | A hand-built onboarding takeover (`inboxOnboardingLogic`, `InboxOnboarding`) that already implements this pattern by hand                                                                                                        |
| Revenue analytics        | `products/revenue_analytics/frontend/settings/RevenueAnalyticsSettings.tsx` | `ProductIntroduction`. No standalone scene, so it needs `scenes: [...]` scoping like web vitals                                                                                                                                  |
| AI gateway               | `products/ai_gateway/frontend/AIGatewayScene.tsx`                           | Hand-rolled "No gateway usage yet" panel                                                                                                                                                                                         |

### Tier 3: sub-surfaces of adopted products

These products read as migrated at the scene level but still ship `ProductIntroduction` one click
deeper, so the product is half-migrated.

| Parent product     | Sub-surface                                                                                                 |
| ------------------ | ----------------------------------------------------------------------------------------------------------- |
| Workflows          | `Channels/MessageChannels.tsx`, `OptOuts/OptOutCategories.tsx`, `TemplateLibrary/MessageTemplatesTable.tsx` |
| Logs               | `components/LogsAlerting/LogsAlertList.tsx`                                                                 |
| Replay vision      | `replay_scanners/components/VisionActionsTab.tsx`                                                           |
| Customer analytics | `components/CustomerJourneys/CustomerJourneysEmptyState.tsx`                                                |

### Tier 4: everything else

Still on `ProductIntroduction`: alerts (`products/alerts/frontend/views/InsightAlerts.tsx`),
subscriptions, pulse, data catalog, engineering analytics, comments, ingestion warnings (v1 and v2),
Max conversation history, and data pipelines destinations and transformations
(`frontend/src/scenes/data-pipelines/DataPipelinesHogFunctions.tsx` covers the last two).

Hand-rolled empty states: review hog, streamlit apps, groups (`GroupsIntroduction`), persons, and
the LLM analytics sessions and evaluations tabs.

Bare string or nothing: notebooks, the data warehouse overview scene, SQL editor, data modeling,
heatmaps, business knowledge, legal documents, MCP gateway, visual review, live debugger, batch
exports, experiments shared metrics, skills community, and several LLM analytics sub-tabs.

## Out of scope

- Per-entity detail and editor scenes. The gate is for product landing surfaces.
- Onboarding (`frontend/src/scenes/onboarding/`), billing, settings, auth, and other platform scenes.
- Staff, instance, and debug scenes.
- Dashboard widget tiles. They are not scenes and cannot use the scene gate, which is why
  `products/error_tracking/frontend/components/SetupPrompt/SetupPrompt.tsx` survives its product's
  migration.
- `products/desktop/`. It is a separate app and does not use the app shell's scene system.

## Picking up an item

1. Read the `building-product-empty-states` skill and the reference adoption.
2. Check whether the product can answer "is it set up?" from event definitions. If so, add a
   `setupProbe` to its manifest so the gate resolves at boot instead of showing a spinner.
3. Delete the old empty state in the same PR. Leaving both means two setup surfaces.
4. Add a story per mode to `frontend/src/lib/components/ProductEmptyState/ProductEmptyState.stories.tsx`.
5. Check the product's existing scene stories. A story that mocks an empty response now renders the
   empty state instead of the scene, which changes what that story covers and can hang the visual
   regression runner on the preview's animation.

Adoptions do not need to be stacked on each other. The platform is already on `master`; each
adoption touches its own product folder plus two shared files
(`frontend/src/products.tsx` and `ProductEmptyState.stories.tsx`), which is the only conflict surface.
