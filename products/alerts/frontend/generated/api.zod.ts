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
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

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
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['zscore'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Rolling window size for calculating mean/std (default: 30)'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['mad'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
                            }),
                            zod.object({
                                multiplier: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                    ),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                type: zod
                                    .enum(['iqr'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Rolling window size for calculating quartiles (default: 30)'),
                            }),
                            zod.object({
                                lower_bound: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Lower bound - values below this are anomalies'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                type: zod
                                    .enum(['threshold'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault),
                                upper_bound: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Upper bound - values above this are anomalies'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ecod'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['copod'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_estimators: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Number of trees in the forest (default: 100)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['isolation_forest'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                method: zod.enum(['largest', 'mean', 'median']).nullish(),
                                n_neighbors: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Number of neighbors to consider (default: 5)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['knn'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_bins: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Number of histogram bins (default: 10)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['hbos'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_neighbors: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Number of neighbors for LOF (default: 20)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['lof'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                    ),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                kernel: zod
                                    .string()
                                    .nullish()
                                    .default(null)
                                    .describe('SVM kernel type (default: \"rbf\")'),
                                nu: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ocsvm'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault
                                    ),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .nullish()
                                            .default(null)
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['pca'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault
                                    ),
                                window: zod
                                    .number()
                                    .nullish()
                                    .default(null)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                        ])
                    )
                    .describe('Sub-detector configurations (minimum 2)'),
                operator: zod.enum(['and', 'or']),
                type: zod.enum(['ensemble']).default(alertsSimulateCreateBodyDetectorConfigOneOneTypeDefault),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['zscore']).default(alertsSimulateCreateBodyDetectorConfigOneTwoTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Rolling window size for calculating mean/std (default: 30)'),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['mad']).default(alertsSimulateCreateBodyDetectorConfigOneThreeTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
            }),
            zod.object({
                multiplier: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                type: zod.enum(['iqr']).default(alertsSimulateCreateBodyDetectorConfigOneFourTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Rolling window size for calculating quartiles (default: 30)'),
            }),
            zod.object({
                lower_bound: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Lower bound - values below this are anomalies'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                type: zod.enum(['threshold']).default(alertsSimulateCreateBodyDetectorConfigOneFiveTypeDefault),
                upper_bound: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Upper bound - values above this are anomalies'),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ecod']).default(alertsSimulateCreateBodyDetectorConfigOneSixTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['copod']).default(alertsSimulateCreateBodyDetectorConfigOneSevenTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_estimators: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Number of trees in the forest (default: 100)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['isolation_forest']).default(alertsSimulateCreateBodyDetectorConfigOneEightTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                method: zod.enum(['largest', 'mean', 'median']).nullish(),
                n_neighbors: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Number of neighbors to consider (default: 5)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['knn']).default(alertsSimulateCreateBodyDetectorConfigOneNineTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_bins: zod.number().nullish().default(null).describe('Number of histogram bins (default: 10)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['hbos']).default(alertsSimulateCreateBodyDetectorConfigOneOnezeroTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_neighbors: zod.number().nullish().default(null).describe('Number of neighbors for LOF (default: 20)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['lof']).default(alertsSimulateCreateBodyDetectorConfigOneOneoneTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                kernel: zod.string().nullish().default(null).describe('SVM kernel type (default: \"rbf\")'),
                nu: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ocsvm']).default(alertsSimulateCreateBodyDetectorConfigOneOnetwoTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .nullish()
                            .default(null)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .nullish()
                    .default(null)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['pca']).default(alertsSimulateCreateBodyDetectorConfigOneOnethreeTypeDefault),
                window: zod
                    .number()
                    .nullish()
                    .default(null)
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
        .describe('Zero-based index of the series to analyze.'),
    date_from: zod
        .string()
        .nullish()
        .describe(
            "Relative date string for how far back to simulate (e.g. '-24h', '-30d', '-4w'). If not provided, uses the detector's minimum required samples."
        ),
})
