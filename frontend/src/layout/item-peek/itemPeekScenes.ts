import { tryDecodeURIComponent } from 'lib/utils/url'
import { SceneExport, SceneParams } from 'scenes/sceneTypes'

export interface ItemPeekSceneConfig {
    /** Loads a peek-safe export, for a scene that reads its item from the URL and so cannot render twice. */
    load?: () => Promise<{ scene: SceneExport<any> }>
    /** Replaces the scene's own `paramsToProps`, for a scene whose logic writes the URL when it is allowed to. */
    paramsToProps?: (params: SceneParams) => Record<string, any>
    /** Peeks a route with a fixed segment after its id, for an item that lives under another, such as a source's schema. */
    nestedRoutes?: boolean
}

/**
 * The detail scenes a link can open in the peek drawer, keyed by scene id.
 * A scene here renders through its own `SceneExport`, so its logic must be keyed by the props
 * `paramsToProps` builds and must not take its item from the URL. Scenes that create, edit or
 * configure something stay out: a peek is for looking at an item, not changing it.
 */
export const ITEM_PEEK_SCENES: Record<string, ItemPeekSceneConfig> = {
    Action: {},
    AIObservabilityDataset: {},
    AIObservabilityEvaluation: {},
    AIObservabilityPrompt: {},
    AIObservabilityScorer: {},
    Approval: {},
    AutoresearchPipeline: {},
    BatchExport: {},
    Broadcast: {},
    BusinessIntelligence: {},
    BusinessKnowledgeLibrary: {},
    BusinessKnowledgeSource: {},
    CanvasDetail: {},
    Cohort: {},
    CrossProjectDashboard: {},
    CustomerAnalyticsAccount: {},
    Dashboard: {},
    DashboardV2: {},
    DataCatalogMetric: {},
    DataWarehouseSource: {},
    DataWarehouseSourceSchema: { nestedRoutes: true },
    EarlyAccessFeature: {},
    ErrorTrackingIssue: {},
    EventDefinition: {},
    Experiment: {},
    ExperimentsSharedMetric: {},
    FeatureFlag: {},
    Group: {},
    Heatmap: {},
    HogFunction: {},
    Insight: {
        load: () => import('products/product_analytics/frontend/insights/insightScene/InsightItemPeek'),
    },
    LegacyPlugin: {},
    LogsAlertDetail: {},
    LogsRetentionDetail: {},
    LogsSamplingDetail: {},
    MCPAnalyticsToolDetail: {},
    MCPAnalyticsUser: {},
    McpGatewayAgent: {},
    McpGatewayMember: {},
    McpGatewayServer: {},
    NodeDetail: {},
    Notebook: {},
    OAuthApplication: {},
    Person: {
        // The person scene writes its tab into the URL when `syncWithUrl` is on, which would move the page under the drawer.
        paramsToProps: ({ params: { _: rawUrlId } }) => ({
            syncWithUrl: false,
            urlId: tryDecodeURIComponent(rawUrlId),
        }),
    },
    PlatformAlert: {},
    ProductTour: {},
    PropertyDefinition: {},
    Release: {},
    ReplayPlaylist: {},
    ReplaySingle: {},
    ReusableWidget: {},
    SessionProfile: {},
    Skill: {},
    StreamlitApp: {},
    Subscription: {},
    SupportTicketDetail: {},
    Survey: {},
    TaskSpace: {},
    TracingRetentionDetail: {},
    TransactionalCodeEmail: {},
    TransactionalEmailLogEntry: {},
    VisualReviewRun: {},
    Workflow: {},
    WorkflowsEmailDomain: {},
}
