/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const PaginatedAlertListApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PaginatedAlertListApi = zod.input<typeof PaginatedAlertListApi>
export type PaginatedAlertListApiOutput = zod.output<typeof PaginatedAlertListApi>

export const AlertApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type AlertApi = zod.input<typeof AlertApi>
export type AlertApiOutput = zod.output<typeof AlertApi>

export const PatchedAlertApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PatchedAlertApi = zod.input<typeof PatchedAlertApi>
export type PatchedAlertApiOutput = zod.output<typeof PatchedAlertApi>

export const FailedDeliveryChannelsEnumApi = zod
    .enum(['email', 'destination'])
    .describe('\* `email` - email\n\* `destination` - destination')

export type FailedDeliveryChannelsEnumApi = zod.input<typeof FailedDeliveryChannelsEnumApi>
export type FailedDeliveryChannelsEnumApiOutput = zod.output<typeof FailedDeliveryChannelsEnumApi>

export const AlertTestDeliveryResponseApi = zod.object({
    destination_count: zod.number().describe('Number of active destinations queued for test delivery.'),
    email_recipient_count: zod.number().describe('Number of subscribed users sent a test email.'),
    failed_delivery_channels: zod
        .array(FailedDeliveryChannelsEnumApi)
        .describe('Configured delivery channels that failed to schedule or send.'),
})

export type AlertTestDeliveryResponseApi = zod.input<typeof AlertTestDeliveryResponseApi>
export type AlertTestDeliveryResponseApiOutput = zod.output<typeof AlertTestDeliveryResponseApi>

export const PreprocessingConfigApi = zod.object({
    diffs_n: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
    lags_n: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
    smooth_n: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'),
})

export type PreprocessingConfigApi = zod.input<typeof PreprocessingConfigApi>
export type PreprocessingConfigApiOutput = zod.output<typeof PreprocessingConfigApi>

export const zScoreDetectorConfigApiTypeDefault = `zscore`

export const ZScoreDetectorConfigApi = zod.object({
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'),
    type: zod.enum(['zscore']).default(zScoreDetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Rolling window size for calculating mean\/std (default: 30)'),
})

export type ZScoreDetectorConfigApi = zod.input<typeof ZScoreDetectorConfigApi>
export type ZScoreDetectorConfigApiOutput = zod.output<typeof ZScoreDetectorConfigApi>

export const mADDetectorConfigApiTypeDefault = `mad`

export const MADDetectorConfigApi = zod.object({
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'),
    type: zod.enum(['mad']).default(mADDetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Rolling window size for calculating median\/MAD (default: 30)'),
})

export type MADDetectorConfigApi = zod.input<typeof MADDetectorConfigApi>
export type MADDetectorConfigApiOutput = zod.output<typeof MADDetectorConfigApi>

export const iQRDetectorConfigApiTypeDefault = `iqr`

export const IQRDetectorConfigApi = zod.object({
    multiplier: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    type: zod.enum(['iqr']).default(iQRDetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Rolling window size for calculating quartiles (default: 30)'),
})

export type IQRDetectorConfigApi = zod.input<typeof IQRDetectorConfigApi>
export type IQRDetectorConfigApiOutput = zod.output<typeof IQRDetectorConfigApi>

export const thresholdDetectorConfigApiTypeDefault = `threshold`

export const ThresholdDetectorConfigApi = zod.object({
    lower_bound: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Lower bound - values below this are anomalies'),
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    type: zod.enum(['threshold']).default(thresholdDetectorConfigApiTypeDefault),
    upper_bound: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Upper bound - values above this are anomalies'),
})

export type ThresholdDetectorConfigApi = zod.input<typeof ThresholdDetectorConfigApi>
export type ThresholdDetectorConfigApiOutput = zod.output<typeof ThresholdDetectorConfigApi>

export const eCODDetectorConfigApiTypeDefault = `ecod`

export const ECODDetectorConfigApi = zod.object({
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Anomaly probability threshold (default: 0.9)'),
    type: zod.enum(['ecod']).default(eCODDetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
        ),
})

export type ECODDetectorConfigApi = zod.input<typeof ECODDetectorConfigApi>
export type ECODDetectorConfigApiOutput = zod.output<typeof ECODDetectorConfigApi>

export const cOPODDetectorConfigApiTypeDefault = `copod`

export const COPODDetectorConfigApi = zod.object({
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Anomaly probability threshold (default: 0.9)'),
    type: zod.enum(['copod']).default(cOPODDetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
        ),
})

export type COPODDetectorConfigApi = zod.input<typeof COPODDetectorConfigApi>
export type COPODDetectorConfigApiOutput = zod.output<typeof COPODDetectorConfigApi>

export const isolationForestDetectorConfigApiTypeDefault = `isolation_forest`

export const IsolationForestDetectorConfigApi = zod.object({
    n_estimators: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Number of trees in the forest (default: 100)'),
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Anomaly probability threshold (default: 0.9)'),
    type: zod.enum(['isolation_forest']).default(isolationForestDetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
        ),
})

export type IsolationForestDetectorConfigApi = zod.input<typeof IsolationForestDetectorConfigApi>
export type IsolationForestDetectorConfigApiOutput = zod.output<typeof IsolationForestDetectorConfigApi>

export const MethodApi = zod.enum(['largest', 'mean', 'median'])

export type MethodApi = zod.input<typeof MethodApi>
export type MethodApiOutput = zod.output<typeof MethodApi>

export const kNNDetectorConfigApiTypeDefault = `knn`

export const KNNDetectorConfigApi = zod.object({
    method: zod
        .union([MethodApi, zod.null()])
        .optional()
        .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
    n_neighbors: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Number of neighbors to consider (default: 5)'),
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Anomaly probability threshold (default: 0.9)'),
    type: zod.enum(['knn']).default(kNNDetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
        ),
})

export type KNNDetectorConfigApi = zod.input<typeof KNNDetectorConfigApi>
export type KNNDetectorConfigApiOutput = zod.output<typeof KNNDetectorConfigApi>

export const hBOSDetectorConfigApiTypeDefault = `hbos`

export const HBOSDetectorConfigApi = zod.object({
    n_bins: zod.union([zod.number(), zod.null()]).optional().describe('Number of histogram bins (default: 10)'),
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Anomaly probability threshold (default: 0.9)'),
    type: zod.enum(['hbos']).default(hBOSDetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
        ),
})

export type HBOSDetectorConfigApi = zod.input<typeof HBOSDetectorConfigApi>
export type HBOSDetectorConfigApiOutput = zod.output<typeof HBOSDetectorConfigApi>

export const lOFDetectorConfigApiTypeDefault = `lof`

export const LOFDetectorConfigApi = zod.object({
    n_neighbors: zod.union([zod.number(), zod.null()]).optional().describe('Number of neighbors for LOF (default: 20)'),
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Anomaly probability threshold (default: 0.9)'),
    type: zod.enum(['lof']).default(lOFDetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
        ),
})

export type LOFDetectorConfigApi = zod.input<typeof LOFDetectorConfigApi>
export type LOFDetectorConfigApiOutput = zod.output<typeof LOFDetectorConfigApi>

export const oCSVMDetectorConfigApiTypeDefault = `ocsvm`

export const OCSVMDetectorConfigApi = zod.object({
    kernel: zod.union([zod.string(), zod.null()]).optional().describe('SVM kernel type (default: \"rbf\")'),
    nu: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Upper bound on training errors fraction (default: 0.1)'),
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Anomaly probability threshold (default: 0.9)'),
    type: zod.enum(['ocsvm']).default(oCSVMDetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
        ),
})

export type OCSVMDetectorConfigApi = zod.input<typeof OCSVMDetectorConfigApi>
export type OCSVMDetectorConfigApiOutput = zod.output<typeof OCSVMDetectorConfigApi>

export const pCADetectorConfigApiTypeDefault = `pca`

export const PCADetectorConfigApi = zod.object({
    preprocessing: zod
        .union([PreprocessingConfigApi, zod.null()])
        .optional()
        .describe('Preprocessing transforms applied before detection'),
    threshold: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Anomaly probability threshold (default: 0.9)'),
    type: zod.enum(['pca']).default(pCADetectorConfigApiTypeDefault),
    window: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe(
            'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
        ),
})

export type PCADetectorConfigApi = zod.input<typeof PCADetectorConfigApi>
export type PCADetectorConfigApiOutput = zod.output<typeof PCADetectorConfigApi>

export const EnsembleOperatorApi = zod.enum(['and', 'or'])

export type EnsembleOperatorApi = zod.input<typeof EnsembleOperatorApi>
export type EnsembleOperatorApiOutput = zod.output<typeof EnsembleOperatorApi>

export const ensembleDetectorConfigApiTypeDefault = `ensemble`

export const EnsembleDetectorConfigApi = zod.object({
    detectors: zod
        .array(
            zod.union([
                ZScoreDetectorConfigApi,
                MADDetectorConfigApi,
                IQRDetectorConfigApi,
                ThresholdDetectorConfigApi,
                ECODDetectorConfigApi,
                COPODDetectorConfigApi,
                IsolationForestDetectorConfigApi,
                KNNDetectorConfigApi,
                HBOSDetectorConfigApi,
                LOFDetectorConfigApi,
                OCSVMDetectorConfigApi,
                PCADetectorConfigApi,
            ])
        )
        .describe('Sub-detector configurations (minimum 2)'),
    operator: EnsembleOperatorApi.describe('How to combine sub-detector results'),
    type: zod.enum(['ensemble']).default(ensembleDetectorConfigApiTypeDefault),
})

export type EnsembleDetectorConfigApi = zod.input<typeof EnsembleDetectorConfigApi>
export type EnsembleDetectorConfigApiOutput = zod.output<typeof EnsembleDetectorConfigApi>

export const DetectorConfigApi = zod
    .union([
        EnsembleDetectorConfigApi,
        ZScoreDetectorConfigApi,
        MADDetectorConfigApi,
        IQRDetectorConfigApi,
        ThresholdDetectorConfigApi,
        ECODDetectorConfigApi,
        COPODDetectorConfigApi,
        IsolationForestDetectorConfigApi,
        KNNDetectorConfigApi,
        HBOSDetectorConfigApi,
        LOFDetectorConfigApi,
        OCSVMDetectorConfigApi,
        PCADetectorConfigApi,
    ])
    .describe('Detector configuration types')

export type DetectorConfigApi = zod.input<typeof DetectorConfigApi>
export type DetectorConfigApiOutput = zod.output<typeof DetectorConfigApi>

export const trendsAlertConfigApiTypeDefault = `TrendsAlertConfig`

export const TrendsAlertConfigApi = zod.object({
    check_ongoing_interval: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe('When true, evaluate the current (still incomplete) time interval in addition to completed ones.'),
    series_index: zod.number().describe("Zero-based index of the series in the insight's query to monitor."),
    type: zod.enum(['TrendsAlertConfig']).default(trendsAlertConfigApiTypeDefault),
})

export type TrendsAlertConfigApi = zod.input<typeof TrendsAlertConfigApi>
export type TrendsAlertConfigApiOutput = zod.output<typeof TrendsAlertConfigApi>

export const HogQLAlertEvaluationApi = zod.enum(['last_row', 'first_row', 'any_row'])

export type HogQLAlertEvaluationApi = zod.input<typeof HogQLAlertEvaluationApi>
export type HogQLAlertEvaluationApiOutput = zod.output<typeof HogQLAlertEvaluationApi>

export const hogQLAlertConfigApiTypeDefault = `HogQLAlertConfig`

export const HogQLAlertConfigApi = zod.object({
    column: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            'Name of the result column to evaluate. When unset, the single numeric column is used (an error if the result has more than one numeric column).'
        ),
    evaluation: HogQLAlertEvaluationApi.describe(
        'How to read the result rows — an explicit choice, no implicit default.'
    ),
    label_column: zod
        .union([zod.string(), zod.null()])
        .optional()
        .describe(
            'Column whose value labels the evaluated row(s) in breach messages: every row in `any_row` mode, or the single evaluated row in `last_row`\/`first_row`. When unset, the first non-evaluated column is used, falling back to the row number (any_row) or the value column name (last_row\/first_row).'
        ),
    type: zod.enum(['HogQLAlertConfig']).default(hogQLAlertConfigApiTypeDefault),
})

export type HogQLAlertConfigApi = zod.input<typeof HogQLAlertConfigApi>
export type HogQLAlertConfigApiOutput = zod.output<typeof HogQLAlertConfigApi>

export const FunnelConversionMetricApi = zod.enum(['conversion_from_start', 'conversion_from_previous'])

export type FunnelConversionMetricApi = zod.input<typeof FunnelConversionMetricApi>
export type FunnelConversionMetricApiOutput = zod.output<typeof FunnelConversionMetricApi>

export const funnelsAlertConfigApiTypeDefault = `FunnelsAlertConfig`

export const FunnelsAlertConfigApi = zod.object({
    check_ongoing_interval: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe(
            'When true, evaluate the current (still in-progress) period; by default only completed periods are used.'
        ),
    funnel_step: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Zero-based step index to evaluate. Null = the last step (overall conversion).'),
    metric: FunnelConversionMetricApi,
    type: zod.enum(['FunnelsAlertConfig']).default(funnelsAlertConfigApiTypeDefault),
})

export type FunnelsAlertConfigApi = zod.input<typeof FunnelsAlertConfigApi>
export type FunnelsAlertConfigApiOutput = zod.output<typeof FunnelsAlertConfigApi>

export const metricsAlertConfigApiTypeDefault = `MetricsAlertConfig`

export const MetricsAlertConfigApi = zod.object({
    check_ongoing_interval: zod
        .union([zod.boolean(), zod.null()])
        .optional()
        .describe(
            'When true, anchor on the trailing (possibly still accumulating) bucket instead of the last complete one.'
        ),
    type: zod.enum(['MetricsAlertConfig']).default(metricsAlertConfigApiTypeDefault),
})

export type MetricsAlertConfigApi = zod.input<typeof MetricsAlertConfigApi>
export type MetricsAlertConfigApiOutput = zod.output<typeof MetricsAlertConfigApi>

export const AlertConfigUnionApi = zod
    .union([TrendsAlertConfigApi, HogQLAlertConfigApi, FunnelsAlertConfigApi, MetricsAlertConfigApi])
    .describe(
        'Per-insight-kind alert config, discriminated by ``type`` — keeps the OpenAPI (and the\ngenerated frontend types and MCP tool schemas) in sync with every kind alerts support.'
    )

export type AlertConfigUnionApi = zod.input<typeof AlertConfigUnionApi>
export type AlertConfigUnionApiOutput = zod.output<typeof AlertConfigUnionApi>

export const alertSimulateApiSeriesIndexDefault = 0

export const AlertSimulateApi = zod.object({
    insight: zod.number().describe('Insight ID to simulate the detector on.'),
    detector_config: DetectorConfigApi.describe('Detector configuration to simulate.'),
    series_index: zod
        .number()
        .default(alertSimulateApiSeriesIndexDefault)
        .describe('Zero-based index of the series to analyze (trends insights only).'),
    date_from: zod
        .string()
        .nullish()
        .describe(
            "Relative date string for how far back to simulate (e.g. '-24h', '-30d', '-4w'). If not provided, uses the detector's minimum required samples. Trends insights only — a SQL query's own rows are the series."
        ),
    config: zod
        .union([AlertConfigUnionApi, zod.null()])
        .optional()
        .describe(
            'Per-insight-kind alert config. For SQL insights, selects the evaluated column and read direction (last_row\/first_row) so the preview matches the alert; ignored for trends.'
        ),
})

export type AlertSimulateApi = zod.input<typeof AlertSimulateApi>
export type AlertSimulateApiOutput = zod.output<typeof AlertSimulateApi>

export const BreakdownSimulationResultApi = zod.object({
    label: zod.string().describe('Breakdown value label.'),
    data: zod.array(zod.number()).describe('Data values for each point.'),
    dates: zod.array(zod.string()).describe('Date labels for each point.'),
    scores: zod.array(zod.number().nullable()).describe('Anomaly score for each point.'),
    triggered_indices: zod.array(zod.number()).describe('Indices of points flagged as anomalies.'),
    triggered_dates: zod.array(zod.string()).describe('Dates of points flagged as anomalies.'),
    total_points: zod.number().describe('Total number of data points analyzed.'),
    anomaly_count: zod.number().describe('Number of anomalies detected.'),
    sub_detector_scores: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe('Per-sub-detector scores for ensemble detectors.'),
})

export type BreakdownSimulationResultApi = zod.input<typeof BreakdownSimulationResultApi>
export type BreakdownSimulationResultApiOutput = zod.output<typeof BreakdownSimulationResultApi>

export const AlertSimulateResponseApi = zod.object({
    data: zod.array(zod.number()).describe('Data values for each point.'),
    dates: zod.array(zod.string()).describe('Date labels for each point.'),
    scores: zod.array(zod.number().nullable()).describe('Anomaly score for each point (null if insufficient data).'),
    triggered_indices: zod.array(zod.number()).describe('Indices of points flagged as anomalies.'),
    triggered_dates: zod.array(zod.string()).describe('Dates of points flagged as anomalies.'),
    interval: zod.string().nullable().describe('Interval of the trends query (hour, day, week, month).'),
    total_points: zod.number().describe('Total number of data points analyzed.'),
    anomaly_count: zod.number().describe('Number of anomalies detected.'),
    sub_detector_scores: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe("Per-sub-detector scores for ensemble detectors. Each entry has 'type' and 'scores' fields."),
    breakdown_results: zod
        .array(BreakdownSimulationResultApi)
        .optional()
        .describe(
            'Per-breakdown-value simulation results. Present only when the insight has breakdowns (up to 25 values).'
        ),
})

export type AlertSimulateResponseApi = zod.input<typeof AlertSimulateResponseApi>
export type AlertSimulateResponseApiOutput = zod.output<typeof AlertSimulateResponseApi>

export const PaginatedThresholdWithAlertListApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type PaginatedThresholdWithAlertListApi = zod.input<typeof PaginatedThresholdWithAlertListApi>
export type PaginatedThresholdWithAlertListApiOutput = zod.output<typeof PaginatedThresholdWithAlertListApi>

export const ThresholdWithAlertApi = zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export type ThresholdWithAlertApi = zod.input<typeof ThresholdWithAlertApi>
export type ThresholdWithAlertApiOutput = zod.output<typeof ThresholdWithAlertApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const InsightsThresholdBoundsApi = zod.object({
    lower: zod
        .union([zod.number(), zod.null()])
        .optional()
        .describe('Alert fires when the value drops below this number.'),
    upper: zod.union([zod.number(), zod.null()]).optional().describe('Alert fires when the value exceeds this number.'),
})

export type InsightsThresholdBoundsApi = zod.input<typeof InsightsThresholdBoundsApi>
export type InsightsThresholdBoundsApiOutput = zod.output<typeof InsightsThresholdBoundsApi>

export const InsightThresholdTypeApi = zod.enum(['absolute', 'percentage'])

export type InsightThresholdTypeApi = zod.input<typeof InsightThresholdTypeApi>
export type InsightThresholdTypeApiOutput = zod.output<typeof InsightThresholdTypeApi>

export const InsightThresholdApi = zod.object({
    bounds: zod.union([InsightsThresholdBoundsApi, zod.null()]).optional(),
    type: InsightThresholdTypeApi.describe(
        'Whether bounds are compared as absolute values or as percentage change from the previous interval.'
    ),
})

export type InsightThresholdApi = zod.input<typeof InsightThresholdApi>
export type InsightThresholdApiOutput = zod.output<typeof InsightThresholdApi>

export const thresholdApiNameMax = 255

export const ThresholdApi = zod.object({
    id: zod.uuid(),
    created_at: zod.iso.datetime({ offset: true }),
    name: zod.string().max(thresholdApiNameMax).optional().describe('Optional name for the threshold.'),
    configuration: InsightThresholdApi.describe(
        'Threshold bounds and type. Includes bounds (lower\/upper floats) and type (absolute or percentage). For threshold-based alerts (no detector_config), at least one of lower or upper must be set.'
    ),
})

export type ThresholdApi = zod.input<typeof ThresholdApi>
export type ThresholdApiOutput = zod.output<typeof ThresholdApi>

export const AlertConditionTypeApi = zod.enum(['absolute_value', 'relative_increase', 'relative_decrease'])

export type AlertConditionTypeApi = zod.input<typeof AlertConditionTypeApi>
export type AlertConditionTypeApiOutput = zod.output<typeof AlertConditionTypeApi>

export const AlertConditionApi = zod.object({
    type: AlertConditionTypeApi,
})

export type AlertConditionApi = zod.input<typeof AlertConditionApi>
export type AlertConditionApiOutput = zod.output<typeof AlertConditionApi>

export const AlertCheckStateEnumApi = zod
    .enum(['Firing', 'Not firing', 'Errored', 'Snoozed'])
    .describe('\* `Firing` - Firing\n\* `Not firing` - Not firing\n\* `Errored` - Errored\n\* `Snoozed` - Snoozed')

export type AlertCheckStateEnumApi = zod.input<typeof AlertCheckStateEnumApi>
export type AlertCheckStateEnumApiOutput = zod.output<typeof AlertCheckStateEnumApi>

export const InvestigationStatusEnumApi = zod
    .enum(['pending', 'running', 'done', 'failed', 'skipped'])
    .describe(
        '\* `pending` - pending\n\* `running` - running\n\* `done` - done\n\* `failed` - failed\n\* `skipped` - skipped'
    )

export type InvestigationStatusEnumApi = zod.input<typeof InvestigationStatusEnumApi>
export type InvestigationStatusEnumApiOutput = zod.output<typeof InvestigationStatusEnumApi>

export const InvestigationVerdictEnumApi = zod
    .enum(['true_positive', 'false_positive', 'inconclusive'])
    .describe(
        '\* `true_positive` - true_positive\n\* `false_positive` - false_positive\n\* `inconclusive` - inconclusive'
    )

export type InvestigationVerdictEnumApi = zod.input<typeof InvestigationVerdictEnumApi>
export type InvestigationVerdictEnumApiOutput = zod.output<typeof InvestigationVerdictEnumApi>

export const AlertCheckApi = zod.object({
    id: zod.uuid(),
    created_at: zod.iso.datetime({ offset: true }),
    calculated_value: zod.number().nullable(),
    state: AlertCheckStateEnumApi,
    targets_notified: zod.boolean(),
    anomaly_scores: zod.unknown(),
    triggered_points: zod.unknown(),
    triggered_dates: zod.unknown(),
    interval: zod.string().nullable(),
    triggered_metadata: zod.unknown(),
    investigation_status: zod.union([InvestigationStatusEnumApi, zod.null()]),
    investigation_verdict: zod.union([InvestigationVerdictEnumApi, zod.null()]),
    investigation_summary: zod.string().nullable(),
    investigation_notebook_short_id: zod
        .string()
        .nullable()
        .describe('Short ID of the Notebook produced by the investigation agent, when the agent ran for this check.'),
    notification_sent_at: zod.iso.datetime({ offset: true }).nullable(),
    notification_suppressed_by_agent: zod.boolean(),
})

export type AlertCheckApi = zod.input<typeof AlertCheckApi>
export type AlertCheckApiOutput = zod.output<typeof AlertCheckApi>

export const CalculationIntervalEnumApi = zod
    .enum(['real_time', 'every_15_minutes', 'hourly', 'daily', 'weekly', 'monthly'])
    .describe(
        '\* `real_time` - real_time\n\* `every_15_minutes` - every_15_minutes\n\* `hourly` - hourly\n\* `daily` - daily\n\* `weekly` - weekly\n\* `monthly` - monthly'
    )

export type CalculationIntervalEnumApi = zod.input<typeof CalculationIntervalEnumApi>
export type CalculationIntervalEnumApiOutput = zod.output<typeof CalculationIntervalEnumApi>

export const AlertScheduleRestrictionWindowApi = zod.object({
    start: zod
        .string()
        .describe(
            'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
        ),
    end: zod
        .string()
        .describe(
            'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
        ),
})

export type AlertScheduleRestrictionWindowApi = zod.input<typeof AlertScheduleRestrictionWindowApi>
export type AlertScheduleRestrictionWindowApiOutput = zod.output<typeof AlertScheduleRestrictionWindowApi>

export const AlertScheduleRestrictionApi = zod.object({
    blocked_windows: zod
        .array(AlertScheduleRestrictionWindowApi)
        .describe(
            'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
        ),
})

export type AlertScheduleRestrictionApi = zod.input<typeof AlertScheduleRestrictionApi>
export type AlertScheduleRestrictionApiOutput = zod.output<typeof AlertScheduleRestrictionApi>

export const InvestigationInconclusiveActionEnumApi = zod
    .enum(['notify', 'suppress'])
    .describe('\* `notify` - Notify\n\* `suppress` - Suppress')

export type InvestigationInconclusiveActionEnumApi = zod.input<typeof InvestigationInconclusiveActionEnumApi>
export type InvestigationInconclusiveActionEnumApiOutput = zod.output<typeof InvestigationInconclusiveActionEnumApi>

export const SearchMatchTypeEnumApi = zod.enum(['exact', 'similar'])

export type SearchMatchTypeEnumApi = zod.input<typeof SearchMatchTypeEnumApi>
export type SearchMatchTypeEnumApiOutput = zod.output<typeof SearchMatchTypeEnumApi>
