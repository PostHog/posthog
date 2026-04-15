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

export const AlertsListResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsCreateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsRetrieveResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsUpdateResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsPartialUpdateBody = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

export const AlertsPartialUpdateResponse = /* @__PURE__ */ zod
    .record(zod.string(), zod.unknown())
    .describe('Deep/recursive schema (opaque in Zod — use TypeScript types for full shape)')

/**
 * Simulate a detector on an insight's historical data. Read-only — no AlertCheck records are created.
 */
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault = `zscore`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault = `mad`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeMultiplierDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeTypeDefault = `iqr`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourLowerBoundDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourTypeDefault = `threshold`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourUpperBoundDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault = `ecod`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault = `copod`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenNEstimatorsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault = `isolation_forest`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightNNeighborsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault = `knn`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineNBinsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault = `hbos`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroNNeighborsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault = `lof`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneKernelDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneNuDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault = `ocsvm`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault = `pca`
export const alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneTypeDefault = `ensemble`
export const alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneTwoThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneTwoTypeDefault = `zscore`
export const alertsSimulateCreateBodyDetectorConfigOneTwoWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreeThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneThreeTypeDefault = `mad`
export const alertsSimulateCreateBodyDetectorConfigOneThreeWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourMultiplierDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFourTypeDefault = `iqr`
export const alertsSimulateCreateBodyDetectorConfigOneFourWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFiveLowerBoundDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneFiveTypeDefault = `threshold`
export const alertsSimulateCreateBodyDetectorConfigOneFiveUpperBoundDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSixTypeDefault = `ecod`
export const alertsSimulateCreateBodyDetectorConfigOneSixWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneSevenTypeDefault = `copod`
export const alertsSimulateCreateBodyDetectorConfigOneSevenWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightNEstimatorsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneEightTypeDefault = `isolation_forest`
export const alertsSimulateCreateBodyDetectorConfigOneEightWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNineNNeighborsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNineThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneNineTypeDefault = `knn`
export const alertsSimulateCreateBodyDetectorConfigOneNineWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroNBinsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroTypeDefault = `hbos`
export const alertsSimulateCreateBodyDetectorConfigOneOnezeroWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneoneNNeighborsDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneoneThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOneoneTypeDefault = `lof`
export const alertsSimulateCreateBodyDetectorConfigOneOneoneWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoKernelDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoNuDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoTypeDefault = `ocsvm`
export const alertsSimulateCreateBodyDetectorConfigOneOnetwoWindowDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingDiffsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingLagsNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingSmoothNDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreeThresholdDefault = null
export const alertsSimulateCreateBodyDetectorConfigOneOnethreeTypeDefault = `pca`
export const alertsSimulateCreateBodyDetectorConfigOneOnethreeWindowDefault = null
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
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnePreprocessingSmoothNDefault
                                            )
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneThresholdDefault
                                    )
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['zscore'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneTypeDefault),
                                window: zod
                                    .number()
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneWindowDefault)
                                    .describe('Rolling window size for calculating mean/std (default: 30)'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoPreprocessingSmoothNDefault
                                            )
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoThresholdDefault
                                    )
                                    .describe(
                                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                                    ),
                                type: zod
                                    .enum(['mad'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoTypeDefault),
                                window: zod
                                    .number()
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemTwoWindowDefault)
                                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
                            }),
                            zod.object({
                                multiplier: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeMultiplierDefault
                                    )
                                    .describe(
                                        'IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'
                                    ),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreePreprocessingSmoothNDefault
                                            )
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
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemThreeWindowDefault
                                    )
                                    .describe('Rolling window size for calculating quartiles (default: 30)'),
                            }),
                            zod.object({
                                lower_bound: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourLowerBoundDefault
                                    )
                                    .describe('Lower bound - values below this are anomalies'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourPreprocessingSmoothNDefault
                                            )
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
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFourUpperBoundDefault
                                    )
                                    .describe('Upper bound - values above this are anomalies'),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFivePreprocessingSmoothNDefault
                                            )
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ecod'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveTypeDefault),
                                window: zod
                                    .number()
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemFiveWindowDefault)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixPreprocessingSmoothNDefault
                                            )
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['copod'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixTypeDefault),
                                window: zod
                                    .number()
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSixWindowDefault)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_estimators: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenNEstimatorsDefault
                                    )
                                    .describe('Number of trees in the forest (default: 100)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenPreprocessingSmoothNDefault
                                            )
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['isolation_forest'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenTypeDefault),
                                window: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemSevenWindowDefault
                                    )
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                method: zod.enum(['largest', 'mean', 'median']).nullish(),
                                n_neighbors: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightNNeighborsDefault
                                    )
                                    .describe('Number of neighbors to consider (default: 5)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightPreprocessingSmoothNDefault
                                            )
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['knn'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightTypeDefault),
                                window: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemEightWindowDefault
                                    )
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_bins: zod
                                    .number()
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineNBinsDefault)
                                    .describe('Number of histogram bins (default: 10)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNinePreprocessingSmoothNDefault
                                            )
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['hbos'])
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineTypeDefault),
                                window: zod
                                    .number()
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemNineWindowDefault)
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                n_neighbors: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroNNeighborsDefault
                                    )
                                    .describe('Number of neighbors for LOF (default: 20)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroPreprocessingSmoothNDefault
                                            )
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['lof'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroTypeDefault
                                    ),
                                window: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnezeroWindowDefault
                                    )
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                kernel: zod
                                    .string()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneKernelDefault
                                    )
                                    .describe('SVM kernel type (default: \"rbf\")'),
                                nu: zod
                                    .number()
                                    .default(alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneNuDefault)
                                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneonePreprocessingSmoothNDefault
                                            )
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['ocsvm'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneTypeDefault
                                    ),
                                window: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOneoneWindowDefault
                                    )
                                    .describe(
                                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                                    ),
                            }),
                            zod.object({
                                preprocessing: zod
                                    .object({
                                        diffs_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingDiffsNDefault
                                            )
                                            .describe(
                                                'Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'
                                            ),
                                        lags_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingLagsNDefault
                                            )
                                            .describe(
                                                'Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'
                                            ),
                                        smooth_n: zod
                                            .number()
                                            .default(
                                                alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoPreprocessingSmoothNDefault
                                            )
                                            .describe(
                                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                                            ),
                                    })
                                    .nullish(),
                                threshold: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoThresholdDefault
                                    )
                                    .describe('Anomaly probability threshold (default: 0.9)'),
                                type: zod
                                    .enum(['pca'])
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoTypeDefault
                                    ),
                                window: zod
                                    .number()
                                    .default(
                                        alertsSimulateCreateBodyDetectorConfigOneOneDetectorsItemOnetwoWindowDefault
                                    )
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
                            .default(alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneTwoPreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneTwoThresholdDefault)
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['zscore']).default(alertsSimulateCreateBodyDetectorConfigOneTwoTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneTwoWindowDefault)
                    .describe('Rolling window size for calculating mean/std (default: 30)'),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneThreePreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneThreeThresholdDefault)
                    .describe(
                        'Anomaly probability threshold [0-1]. Points above this probability are flagged (default: 0.9)'
                    ),
                type: zod.enum(['mad']).default(alertsSimulateCreateBodyDetectorConfigOneThreeTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneThreeWindowDefault)
                    .describe('Rolling window size for calculating median/MAD (default: 30)'),
            }),
            zod.object({
                multiplier: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneFourMultiplierDefault)
                    .describe('IQR multiplier for fence calculation (default: 1.5, use 3.0 for far outliers)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneFourPreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                type: zod.enum(['iqr']).default(alertsSimulateCreateBodyDetectorConfigOneFourTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneFourWindowDefault)
                    .describe('Rolling window size for calculating quartiles (default: 30)'),
            }),
            zod.object({
                lower_bound: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneFiveLowerBoundDefault)
                    .describe('Lower bound - values below this are anomalies'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneFivePreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                type: zod.enum(['threshold']).default(alertsSimulateCreateBodyDetectorConfigOneFiveTypeDefault),
                upper_bound: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneFiveUpperBoundDefault)
                    .describe('Upper bound - values above this are anomalies'),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneSixPreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneSixThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ecod']).default(alertsSimulateCreateBodyDetectorConfigOneSixTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneSixWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneSevenPreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneSevenThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['copod']).default(alertsSimulateCreateBodyDetectorConfigOneSevenTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneSevenWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_estimators: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneEightNEstimatorsDefault)
                    .describe('Number of trees in the forest (default: 100)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneEightPreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneEightThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['isolation_forest']).default(alertsSimulateCreateBodyDetectorConfigOneEightTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneEightWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                method: zod.enum(['largest', 'mean', 'median']).nullish(),
                n_neighbors: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneNineNNeighborsDefault)
                    .describe('Number of neighbors to consider (default: 5)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneNinePreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneNineThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['knn']).default(alertsSimulateCreateBodyDetectorConfigOneNineTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneNineWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_bins: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroNBinsDefault)
                    .describe('Number of histogram bins (default: 10)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroPreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['hbos']).default(alertsSimulateCreateBodyDetectorConfigOneOnezeroTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnezeroWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                n_neighbors: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOneoneNNeighborsDefault)
                    .describe('Number of neighbors for LOF (default: 20)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOneonePreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOneoneThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['lof']).default(alertsSimulateCreateBodyDetectorConfigOneOneoneTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOneoneWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                kernel: zod
                    .string()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoKernelDefault)
                    .describe('SVM kernel type (default: \"rbf\")'),
                nu: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoNuDefault)
                    .describe('Upper bound on training errors fraction (default: 0.1)'),
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoPreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['ocsvm']).default(alertsSimulateCreateBodyDetectorConfigOneOnetwoTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnetwoWindowDefault)
                    .describe(
                        'Rolling window size — how many historical data points to train on (default: based on calculation interval)'
                    ),
            }),
            zod.object({
                preprocessing: zod
                    .object({
                        diffs_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingDiffsNDefault)
                            .describe('Order of differencing. 0 = raw values, 1 = first-order diffs (default: 0)'),
                        lags_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingLagsNDefault)
                            .describe('Number of lag features. 0 = none, >0 = include n lagged values (default: 0)'),
                        smooth_n: zod
                            .number()
                            .default(alertsSimulateCreateBodyDetectorConfigOneOnethreePreprocessingSmoothNDefault)
                            .describe(
                                'Moving average window size. 0 = no smoothing, >1 = smooth over n points (default: 0)'
                            ),
                    })
                    .nullish(),
                threshold: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnethreeThresholdDefault)
                    .describe('Anomaly probability threshold (default: 0.9)'),
                type: zod.enum(['pca']).default(alertsSimulateCreateBodyDetectorConfigOneOnethreeTypeDefault),
                window: zod
                    .number()
                    .default(alertsSimulateCreateBodyDetectorConfigOneOnethreeWindowDefault)
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

export const AlertsSimulateCreateResponse = /* @__PURE__ */ zod.object({
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
        .array(
            zod.object({
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
        )
        .optional()
        .describe(
            'Per-breakdown-value simulation results. Present only when the insight has breakdowns (up to 25 values).'
        ),
})
