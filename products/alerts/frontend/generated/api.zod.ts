/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const AlertsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep\/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Simulate a detector on an insight's historical data. Read-only — no AlertCheck records are created.
 */
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault = `zscore`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault = `mad`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault = `iqr`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault = `threshold`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault = `ecod`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault = `copod`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault = `isolation_forest`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault = `knn`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault = `hbos`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault = `lof`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault = `ocsvm`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault = `pca`
export const alertsSimulateCreateBodyDetectorConfigOneOneTypeDefault = `ensemble`
export const alertsSimulateCreateBodyDetectorConfigOneTwoTypeDefault = `zscore`
export const alertsSimulateCreateBodyDetectorConfigOneThreeTypeDefault = `mad`
export const alertsSimulateCreateBodyDetectorConfigOneFourTypeDefault = `iqr`
export const alertsSimulateCreateBodyDetectorConfigOneFiveTypeDefault = `threshold`
export const alertsSimulateCreateBodyDetectorConfigOneSixTypeDefault = `ecod`
export const alertsSimulateCreateBodyDetectorConfigOneSevenTypeDefault = `copod`
export const alertsSimulateCreateBodyDetectorConfigOneEightTypeDefault = `isolation_forest`
export const alertsSimulateCreateBodyDetectorConfigOneNineTypeDefault = `knn`
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroTypeDefault = `hbos`
export const alertsSimulateCreateBodyDetectorConfigOneOneoneTypeDefault = `lof`
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoTypeDefault = `ocsvm`
export const alertsSimulateCreateBodyDetectorConfigOneOnethreeTypeDefault = `pca`
export const alertsSimulateCreateBodySeriesIndexDefault = 0
export const alertsSimulateCreateBodyConfigOneOneTypeDefault = `TrendsAlertConfig`
export const alertsSimulateCreateBodyConfigOneTwoTypeDefault = `HogQLAlertConfig`
export const alertsSimulateCreateBodyConfigOneThreeTypeDefault = `FunnelsAlertConfig`
export const alertsSimulateCreateBodyConfigOneFourTypeDefault = `MetricsAlertConfig`

export const AlertsSimulateCreateBody = /* @__PURE__ */ zod.object({
    insight: zod.number().describe('Insight ID to simulate the detector on.'),
    detector_config: zod
        .union([
            zod.object({
                detectors: zod
                    .array(
                        zod.union([
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['zscore'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Rolling window size for calculating mean\/std (default: 30)'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['mad'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Rolling window size for calculating median\/MAD (default: 30)'),
                            }),
                            zod.object({
                                multiplier: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                    ),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                type: zod
                                    .enum(['iqr'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Rolling window size for calculating quartiles (default: 30)'),
                            }),
                            zod.object({
                                lower_bound: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Lower bound - values below this are anomalies'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                type: zod
                                    .enum(['threshold'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault),
                                upper_bound: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Upper bound - values above this are anomalies'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ecod'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['copod'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_estimators: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Number of trees in the forest (default: 100)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['isolation_forest'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                method: zod
                                    .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                                    .optional()
                                    .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
                                n_neighbors: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Number of neighbors to consider (default: 5)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['knn'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_bins: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Number of histogram bins (default: 10)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['hbos'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_neighbors: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Number of neighbors for LOF (default: 20)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['lof'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                    ),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                kernel: zod
                                    .union([zod.string(), zod.null()])
                                    .optional()
                                    .describe('SVM kernel type (default: \"rbf\")'),
                                nu: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ocsvm'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault
                                    ),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .union([
                                        zod.object({
                                            diffs_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                                ),
                                            lags_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                                ),
                                            smooth_n: zod
                                                .union([zod.number(), zod.null()])
                                                .optional()
                                                .describe(
                                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                                ),
                                        }),
                                        zod.null(),
                                    ])
                                    .optional()
                                    .describe('Preprocessing transforms applied before detection'),
                                threshold: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['pca'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault
                                    ),
                                window: zod
                                    .union([zod.number(), zod.null()])
                                    .optional()
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                        ])
                    )
                    .describe('Sub-detector configurations (minimum 2)'),
                operator: zod.enum(['and', 'or']).describe('How to combine sub-detector results'),
                type: zod.enum(['ensemble']).default(alertsSimulateCreateBodyDetectorConfigOneOneTypeDefault),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['zscore']).default(alertsSimulateCreateBodyDetectorConfigOneTwoTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Rolling window size for calculating mean\/std (default: 30)'),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['mad']).default(alertsSimulateCreateBodyDetectorConfigOneThreeTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Rolling window size for calculating median\/MAD (default: 30)'),
            }),
            zod.object({
                multiplier: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                type: zod.enum(['iqr']).default(alertsSimulateCreateBodyDetectorConfigOneFourTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Rolling window size for calculating quartiles (default: 30)'),
            }),
            zod.object({
                lower_bound: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Lower bound - values below this are anomalies'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                type: zod.enum(['threshold']).default(alertsSimulateCreateBodyDetectorConfigOneFiveTypeDefault),
                upper_bound: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Upper bound - values above this are anomalies'),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ecod']).default(alertsSimulateCreateBodyDetectorConfigOneSixTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['copod']).default(alertsSimulateCreateBodyDetectorConfigOneSevenTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_estimators: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Number of trees in the forest (default: 100)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['isolation_forest']).default(alertsSimulateCreateBodyDetectorConfigOneEightTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                method: zod
                    .union([zod.enum(['largest', 'mean', 'median']), zod.null()])
                    .optional()
                    .describe("Distance method: 'largest', 'mean', 'median' (default: 'largest')"),
                n_neighbors: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Number of neighbors to consider (default: 5)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['knn']).default(alertsSimulateCreateBodyDetectorConfigOneNineTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_bins: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Number of histogram bins (default: 10)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['hbos']).default(alertsSimulateCreateBodyDetectorConfigOneOnezeroTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_neighbors: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Number of neighbors for LOF (default: 20)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['lof']).default(alertsSimulateCreateBodyDetectorConfigOneOneoneTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                kernel: zod.union([zod.string(), zod.null()]).optional().describe('SVM kernel type (default: \"rbf\")'),
                nu: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ocsvm']).default(alertsSimulateCreateBodyDetectorConfigOneOnetwoTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .union([
                        zod.object({
                            diffs_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                            lags_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                ),
                            smooth_n: zod
                                .union([zod.number(), zod.null()])
                                .optional()
                                .describe(
                                    'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                ),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Preprocessing transforms applied before detection'),
                threshold: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['pca']).default(alertsSimulateCreateBodyDetectorConfigOneOnethreeTypeDefault),
                window: zod
                    .union([zod.number(), zod.null()])
                    .optional()
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
        ])
        .describe('Detector configuration types')
        .describe('Detector configuration to simulate.'),
    series_index: zod
        .number()
        .default(alertsSimulateCreateBodySeriesIndexDefault)
        .describe('Zero-based index of the series to analyze (trends insights only).'),
    date_from: zod
        .string()
        .nullish()
        .describe(
            "Relative date string for how far back to simulate (e.g. '-24h', '-30d', '-4w'). If not provided, uses the detector's minimum required samples. Trends insights only — a SQL query's own rows are the series."
        ),
    config: zod
        .union([
            zod
                .union([
                    zod.object({
                        check_ongoing_interval: zod
                            .union([zod.boolean(), zod.null()])
                            .optional()
                            .describe(
                                'When true, evaluate the current (still incomplete) time interval in addition to completed ones.'
                            ),
                        series_index: zod
                            .number()
                            .describe("Zero-based index of the series in the insight's query to monitor."),
                        type: zod.enum(['TrendsAlertConfig']).default(alertsSimulateCreateBodyConfigOneOneTypeDefault),
                    }),
                    zod.object({
                        column: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'Name of the result column to evaluate. When unset, the single numeric column is used (an error if the result has more than one numeric column).'
                            ),
                        evaluation: zod
                            .enum(['last_row', 'first_row', 'any_row'])
                            .describe('How to read the result rows — an explicit choice, no implicit default.'),
                        label_column: zod
                            .union([zod.string(), zod.null()])
                            .optional()
                            .describe(
                                'Column whose value labels the evaluated row(s) in breach messages: every row in `any_row` mode, or the single evaluated row in `last_row`\/`first_row`. When unset, the first non-evaluated column is used, falling back to the row number (any_row) or the value column name (last_row\/first_row).'
                            ),
                        type: zod.enum(['HogQLAlertConfig']).default(alertsSimulateCreateBodyConfigOneTwoTypeDefault),
                    }),
                    zod.object({
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
                        metric: zod.enum(['conversion_from_start', 'conversion_from_previous']),
                        type: zod
                            .enum(['FunnelsAlertConfig'])
                            .default(alertsSimulateCreateBodyConfigOneThreeTypeDefault),
                    }),
                    zod.object({
                        check_ongoing_interval: zod
                            .union([zod.boolean(), zod.null()])
                            .optional()
                            .describe(
                                'When true, anchor on the trailing (possibly still accumulating) bucket instead of the last complete one.'
                            ),
                        type: zod
                            .enum(['MetricsAlertConfig'])
                            .default(alertsSimulateCreateBodyConfigOneFourTypeDefault),
                    }),
                ])
                .describe(
                    'Per-insight-kind alert config, discriminated by ``type`` — keeps the OpenAPI (and the\ngenerated frontend types and MCP tool schemas) in sync with every kind alerts support.'
                ),
            zod.null(),
        ])
        .optional()
        .describe(
            'Per-insight-kind alert config. For SQL insights, selects the evaluated column and read direction (last_row\/first_row) so the preview matches the alert; ignored for trends.'
        ),
})

/**
 * Simulate a forecast on an insight's historical data. Read-only — no AlertCheck records are created.
 */
export const alertsSimulateForecastCreateBodyForecastConfigOneEngineDefault = `prophet`
export const alertsSimulateForecastCreateBodyForecastConfigOneTypeDefault = `ForecastConfig`
export const alertsSimulateForecastCreateBodySeriesIndexDefault = 0

export const AlertsSimulateForecastCreateBody = /* @__PURE__ */ zod.object({
    insight: zod.number().describe('Insight ID to simulate the forecast on.'),
    forecast_config: zod
        .object({
            condition: zod.enum(['future_breach', 'band_deviation', 'target_by_date']),
            direction: zod
                .union([zod.enum(['both', 'above', 'below']), zod.null()])
                .optional()
                .describe('Which way a deviation has to go to count (band_deviation only). Default both.'),
            engine: zod.literal('prophet').default(alertsSimulateForecastCreateBodyForecastConfigOneEngineDefault),
            error_mode: zod
                .union([zod.enum(['prediction_interval', 'relative', 'absolute']), zod.null()])
                .optional()
                .describe(
                    'How a deviation from the forecast is measured (band_deviation only). Default prediction_interval.'
                ),
            error_threshold_abs: zod
                .union([zod.number(), zod.null()])
                .optional()
                .describe("Distance from the forecast that counts, in the metric's own units (absolute mode only)."),
            error_threshold_pct: zod
                .union([zod.number(), zod.null()])
                .optional()
                .describe(
                    'Distance from the forecast that counts, as a share of it, e.g. 0.2 for 20% (relative mode only).'
                ),
            horizon: zod
                .union([zod.number(), zod.null()])
                .optional()
                .describe(
                    "How many future intervals to forecast when checking for a threshold breach (future_breach only). Default 7. The forecast can reach at most 6 months ahead, so the limit depends on the insight's interval."
                ),
            interval_width: zod
                .union([zod.number(), zod.null()])
                .optional()
                .describe('Width of the forecast uncertainty band as a fraction, e.g. 0.8 or 0.95 (default 0.95).'),
            score_threshold: zod
                .union([zod.number(), zod.null()])
                .optional()
                .describe(
                    "How far past the band's edge a value must sit to count, in band half-widths, from 0 to 3 (prediction_interval mode only). 0 fires as soon as a value leaves the range, 1 waits for a full half-width beyond it, and a well-calibrated band stops firing at all above about 2. Not a probability, and not bounded at 1. Half-widths rather than training residuals: those exist only when the engine runs with history, which is the preview path, and a scheduled check does not. The band already carries the residual scale, since Prophet built it from them."
                ),
            sensitivity: zod
                .union([zod.enum(['forecast', 'best_case']), zod.null()])
                .optional()
                .describe(
                    'Which line the comparison reads. Defaults to the point forecast for future_breach, and to best_case for target_by_date. Ignored by band_deviation. Distinct from `score_threshold`, which decides how far outside the band counts, not which line is read.'
                ),
            target: zod
                .union([zod.number(), zod.null()])
                .optional()
                .describe('Value the metric must reach or stay under (target_by_date only).'),
            target_date: zod
                .union([zod.string(), zod.null()])
                .optional()
                .describe('ISO date the target must be met by (target_by_date only).'),
            target_direction: zod
                .union([zod.enum(['at_least', 'at_most']), zod.null()])
                .optional()
                .describe('Which side of `target` is acceptable (target_by_date only).'),
            type: zod.literal('ForecastConfig').default(alertsSimulateForecastCreateBodyForecastConfigOneTypeDefault),
        })
        .describe('Forecast configuration to simulate.'),
    series_index: zod
        .number()
        .default(alertsSimulateForecastCreateBodySeriesIndexDefault)
        .describe('Zero-based index of the series to analyze (trends insights only).'),
    date_from: zod
        .string()
        .nullish()
        .describe(
            "Relative date string for how far back to simulate (e.g. '-24h', '-30d', '-4w'). If not provided, uses the forecast's minimum required samples. Trends insights only."
        ),
})
