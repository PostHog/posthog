from collections.abc import Callable

from posthog.hogql.ast import ArrayType, BooleanType, StringType
from posthog.hogql.base import UnknownType

from .core import HogQLFunctionMeta

COMBINATORS = {
    "If": {"allowedSuffixes": [], "argMap": lambda min, max: [min + 1, max + 1]},
    "Array": {"allowedSuffixes": ["If", "OrDefault", "OrNull"], "argMap": lambda min, max: [min, max]},
    "Map": {"allowedSuffixes": ["If", "OrDefault", "OrNull"], "argMap": lambda min, max: [min, max]},
    "State": {"allowedSuffixes": ["If", "OrDefault", "OrNull"], "argMap": lambda min, max: [min, max]},
    "Merge": {"allowedSuffixes": ["If", "OrDefault", "OrNull"], "argMap": lambda min, max: [min, max]},
    "ForEach": {"allowedSuffixes": ["If", "OrDefault", "OrNull"], "argMap": lambda min, max: [min, max]},
    "OrDefault": {"allowedSuffixes": ["If"], "argMap": lambda min, max: [min, max]},
    "OrNull": {"allowedSuffixes": ["If"], "argMap": lambda min, max: [min, max]},
    "ArgMin": {"allowedSuffixes": ["If", "OrDefault", "OrNull"], "argMap": lambda min, max: [min + 1, max + 1]},
    "ArgMax": {"allowedSuffixes": ["If", "OrDefault", "OrNull"], "argMap": lambda min, max: [min + 1, max + 1]},
}

COMBINATOR_AGGREGATIONS = {
    "avg": HogQLFunctionMeta("avg", 1, 1, aggregate=True),
    "sum": HogQLFunctionMeta("sum", 1, 1, aggregate=True),
    "min": HogQLFunctionMeta("min", 1, 1, aggregate=True),
    "max": HogQLFunctionMeta("max", 1, 1, aggregate=True),
    "count": HogQLFunctionMeta("count", 0, 1, aggregate=True),
    "countDistinct": HogQLFunctionMeta("countDistinct", 1, 1, aggregate=True),
    "median": HogQLFunctionMeta("median", 1, 1, aggregate=True),
}


def _generate_suffix_combinations(
    base_name: str, base_meta: HogQLFunctionMeta, current_suffixes: list[str] | None = None
):
    result = {}

    if current_suffixes is None:
        current_suffixes = []

    if current_suffixes:
        func_name = base_name + "".join(current_suffixes)
        # Calculate new parameter ranges based on suffix rules
        min_params, max_params = base_meta.min_args, base_meta.max_args
        for suffix in current_suffixes:
            if suffix in COMBINATORS:
                arg_map: Callable[[int, int | None], list[int]] = COMBINATORS[suffix]["argMap"]  # type: ignore
                min_params, max_params = arg_map(min_params, max_params)

        result[func_name] = HogQLFunctionMeta(func_name, min_params, max_params, aggregate=True)

    if not current_suffixes:
        available_suffixes = list(COMBINATORS.keys())
    else:
        last_suffix = current_suffixes[-1]
        allowed_suffixes: list[str] = COMBINATORS.get(last_suffix, {}).get("allowedSuffixes", [])  # type: ignore
        available_suffixes = allowed_suffixes

    for suffix in available_suffixes:
        if suffix not in current_suffixes:
            nested_result = _generate_suffix_combinations(base_name, base_meta, [*current_suffixes, suffix])
            result.update(nested_result)

    return result


def generate_combinator_suffix_combinations():
    result = {}

    for base_name, base_meta in COMBINATOR_AGGREGATIONS.items():
        combinations = _generate_suffix_combinations(base_name, base_meta)
        result.update(combinations)

    return result


# Permitted HogQL aggregations
# Keep in sync with the posthog.com repository: contents/docs/sql/aggregations.mdx
HOGQL_AGGREGATIONS: dict[str, HogQLFunctionMeta] = {
    # Generated combinator functions
    **generate_combinator_suffix_combinations(),
    # Standard aggregate functions
    "count": HogQLFunctionMeta("count", 0, 1, aggregate=True, case_sensitive=False),
    "countIf": HogQLFunctionMeta("countIf", 1, 2, aggregate=True),
    "countState": HogQLFunctionMeta("countState", 0, 1, aggregate=True),
    "countMerge": HogQLFunctionMeta("countMerge", 1, 1, aggregate=True),
    "countStateIf": HogQLFunctionMeta("countStateIf", 1, 2, aggregate=True),
    "countDistinctIf": HogQLFunctionMeta("countDistinctIf", 1, 2, aggregate=True),
    "countMapIf": HogQLFunctionMeta("countMapIf", 2, 3, aggregate=True),
    "min": HogQLFunctionMeta("min", 1, 1, aggregate=True, case_sensitive=False),
    "minIf": HogQLFunctionMeta("minIf", 2, 2, aggregate=True),
    "max": HogQLFunctionMeta("max", 1, 1, aggregate=True, case_sensitive=False),
    "maxIf": HogQLFunctionMeta("maxIf", 2, 2, aggregate=True),
    "sum": HogQLFunctionMeta("sum", 1, 1, aggregate=True, case_sensitive=False),
    "sumForEach": HogQLFunctionMeta("sumForEach", 1, 1, aggregate=True),
    "minForEach": HogQLFunctionMeta("minForEach", 1, 1, aggregate=True),
    "sumIf": HogQLFunctionMeta("sumIf", 2, 2, aggregate=True),
    "avg": HogQLFunctionMeta("avg", 1, 1, aggregate=True, case_sensitive=False),
    "avgIf": HogQLFunctionMeta("avgIf", 2, 2, aggregate=True),
    "avgMap": HogQLFunctionMeta("avgMap", 1, 1, aggregate=True),
    "avgMapIf": HogQLFunctionMeta("avgMapIf", 2, 3, aggregate=True),
    "avgMapState": HogQLFunctionMeta("avgMapState", 2, 3, aggregate=True),
    "avgMapMerge": HogQLFunctionMeta("avgMapMerge", 1, 1, aggregate=True),
    "avgMapMergeIf": HogQLFunctionMeta("avgMapMergeIf", 2, 2, aggregate=True),
    "any": HogQLFunctionMeta("any", 1, 1, aggregate=True),
    "anyIf": HogQLFunctionMeta("anyIf", 2, 2, aggregate=True),
    "stddevPop": HogQLFunctionMeta("stddevPop", 1, 1, aggregate=True),
    "stddevPopIf": HogQLFunctionMeta("stddevPopIf", 2, 2, aggregate=True),
    "stddevSamp": HogQLFunctionMeta("stddevSamp", 1, 1, aggregate=True),
    "stddevSampIf": HogQLFunctionMeta("stddevSampIf", 2, 2, aggregate=True),
    "varPop": HogQLFunctionMeta("varPop", 1, 1, aggregate=True),
    "varPopIf": HogQLFunctionMeta("varPopIf", 2, 2, aggregate=True),
    "varSamp": HogQLFunctionMeta("varSamp", 1, 1, aggregate=True),
    "varSampIf": HogQLFunctionMeta("varSampIf", 2, 2, aggregate=True),
    "covarPop": HogQLFunctionMeta("covarPop", 2, 2, aggregate=True),
    "covarPopIf": HogQLFunctionMeta("covarPopIf", 3, 3, aggregate=True),
    "covarSamp": HogQLFunctionMeta("covarSamp", 2, 2, aggregate=True),
    "covarSampIf": HogQLFunctionMeta("covarSampIf", 3, 3, aggregate=True),
    "corr": HogQLFunctionMeta("corr", 2, 2, aggregate=True),
    # PostgreSQL-style aggregate functions
    **{
        name: HogQLFunctionMeta(
            "groupArray",
            1,
            1,
            aggregate=True,
            signatures=[((UnknownType(),), ArrayType(item_type=UnknownType()))],
        )
        for name in ["array_agg", "groupArray"]
    },
    "json_agg": HogQLFunctionMeta(
        "toJSONString(groupArray({}))",
        1,
        1,
        aggregate=True,
        signatures=[((UnknownType(),), StringType())],
        using_placeholder_arguments=True,
    ),
    "string_agg": HogQLFunctionMeta(
        "arrayStringConcat(groupArray({}), {})",
        2,
        2,
        aggregate=True,
        signatures=[((StringType(), StringType()), StringType())],
        using_placeholder_arguments=True,
    ),
    "every": HogQLFunctionMeta(
        "toBool(min({}))",
        1,
        1,
        aggregate=True,
        signatures=[((UnknownType(),), BooleanType())],
        using_placeholder_arguments=True,
    ),
    # ClickHouse-specific aggregate functions
    "anyHeavy": HogQLFunctionMeta("anyHeavy", 1, 1, aggregate=True),
    "anyHeavyIf": HogQLFunctionMeta("anyHeavyIf", 2, 2, aggregate=True),
    "anyLast": HogQLFunctionMeta("anyLast", 1, 1, aggregate=True),
    "anyLastIf": HogQLFunctionMeta("anyLastIf", 2, 2, aggregate=True),
    "argMin": HogQLFunctionMeta("argMin", 2, 2, aggregate=True),
    "argMinIf": HogQLFunctionMeta("argMinIf", 3, 3, aggregate=True),
    "argMax": HogQLFunctionMeta("argMax", 2, 2, aggregate=True),
    "argMaxIf": HogQLFunctionMeta("argMaxIf", 3, 3, aggregate=True),
    "argMinMerge": HogQLFunctionMeta("argMinMerge", 1, 1, aggregate=True),
    "argMaxMerge": HogQLFunctionMeta("argMaxMerge", 1, 1, aggregate=True),
    "avgState": HogQLFunctionMeta("avgState", 1, 1, aggregate=True),
    "avgStateIf": HogQLFunctionMeta("avgStateIf", 2, 2, aggregate=True),
    "avgMerge": HogQLFunctionMeta("avgMerge", 1, 1, aggregate=True),
    "avgMergeIf": HogQLFunctionMeta("avgMergeIf", 2, 2, aggregate=True),
    "avgWeighted": HogQLFunctionMeta("avgWeighted", 2, 2, aggregate=True),
    "avgWeightedIf": HogQLFunctionMeta("avgWeightedIf", 3, 3, aggregate=True),
    "avgArray": HogQLFunctionMeta("avgArrayOrNull", 1, 1, aggregate=True),
    "topK": HogQLFunctionMeta("topK", 1, 1, min_params=1, max_params=1, aggregate=True),
    # "topKIf": HogQLFunctionMeta("topKIf", 2, 2, aggregate=True),
    # "topKWeighted": HogQLFunctionMeta("topKWeighted", 1, 1, aggregate=True),
    # "topKWeightedIf": HogQLFunctionMeta("topKWeightedIf", 2, 2, aggregate=True),
    "groupArrayIf": HogQLFunctionMeta("groupArrayIf", 2, 2, aggregate=True),
    # "groupArrayLast": HogQLFunctionMeta("groupArrayLast", 1, 1, aggregate=True),
    # "groupArrayLastIf": HogQLFunctionMeta("groupArrayLastIf", 2, 2, aggregate=True),
    "groupUniqArray": HogQLFunctionMeta("groupUniqArray", 1, 1, aggregate=True),
    "groupUniqArrayIf": HogQLFunctionMeta("groupUniqArrayIf", 2, 2, aggregate=True),
    "groupArrayInsertAt": HogQLFunctionMeta("groupArrayInsertAt", 2, 2, aggregate=True),
    "groupArrayInsertAtIf": HogQLFunctionMeta("groupArrayInsertAtIf", 3, 3, aggregate=True),
    "groupArrayMovingAvg": HogQLFunctionMeta("groupArrayMovingAvg", 1, 1, aggregate=True),
    "groupArrayMovingAvgIf": HogQLFunctionMeta("groupArrayMovingAvgIf", 2, 2, aggregate=True),
    "groupArrayMovingSum": HogQLFunctionMeta("groupArrayMovingSum", 1, 1, aggregate=True),
    "groupArrayMovingSumIf": HogQLFunctionMeta("groupArrayMovingSumIf", 2, 2, aggregate=True),
    "groupArraySample": HogQLFunctionMeta(
        "groupArraySample",
        1,
        1,
        min_params=1,
        max_params=2,
        aggregate=True,
        signatures=[((UnknownType(),), ArrayType(item_type=UnknownType()))],
    ),
    "groupArraySampleIf": HogQLFunctionMeta(
        "groupArraySampleIf",
        2,
        2,
        min_params=1,
        max_params=2,
        aggregate=True,
        signatures=[((UnknownType(), BooleanType()), ArrayType(item_type=UnknownType()))],
    ),
    "groupBitAnd": HogQLFunctionMeta("groupBitAnd", 1, 1, aggregate=True),
    "groupBitAndIf": HogQLFunctionMeta("groupBitAndIf", 2, 2, aggregate=True),
    "groupBitOr": HogQLFunctionMeta("groupBitOr", 1, 1, aggregate=True),
    "groupBitOrIf": HogQLFunctionMeta("groupBitOrIf", 2, 2, aggregate=True),
    "groupBitXor": HogQLFunctionMeta("groupBitXor", 1, 1, aggregate=True),
    "groupBitXorIf": HogQLFunctionMeta("groupBitXorIf", 2, 2, aggregate=True),
    "groupBitmap": HogQLFunctionMeta("groupBitmap", 1, 1, aggregate=True),
    "groupBitmapIf": HogQLFunctionMeta("groupBitmapIf", 2, 2, aggregate=True),
    "groupBitmapState": HogQLFunctionMeta("groupBitmapState", 1, 1, aggregate=True),
    "groupBitmapAnd": HogQLFunctionMeta("groupBitmapAnd", 1, 1, aggregate=True),
    "groupBitmapAndIf": HogQLFunctionMeta("groupBitmapAndIf", 2, 2, aggregate=True),
    "groupBitmapAndState": HogQLFunctionMeta("groupBitmapAndState", 1, 1, aggregate=True),
    "groupBitmapOr": HogQLFunctionMeta("groupBitmapOr", 1, 1, aggregate=True),
    "groupBitmapOrIf": HogQLFunctionMeta("groupBitmapOrIf", 2, 2, aggregate=True),
    "groupBitmapOrState": HogQLFunctionMeta("groupBitmapOrState", 1, 1, aggregate=True),
    "groupBitmapXor": HogQLFunctionMeta("groupBitmapXor", 1, 1, aggregate=True),
    "groupBitmapXorIf": HogQLFunctionMeta("groupBitmapXorIf", 2, 2, aggregate=True),
    "sumWithOverflow": HogQLFunctionMeta("sumWithOverflow", 1, 1, aggregate=True),
    "sumWithOverflowIf": HogQLFunctionMeta("sumWithOverflowIf", 2, 2, aggregate=True),
    "deltaSum": HogQLFunctionMeta("deltaSum", 1, 1, aggregate=True),
    "deltaSumIf": HogQLFunctionMeta("deltaSumIf", 2, 2, aggregate=True),
    "deltaSumTimestamp": HogQLFunctionMeta("deltaSumTimestamp", 2, 2, aggregate=True),
    "deltaSumTimestampIf": HogQLFunctionMeta("deltaSumTimestampIf", 3, 3, aggregate=True),
    "sumMap": HogQLFunctionMeta("sumMap", 1, 2, aggregate=True),
    "sumMapIf": HogQLFunctionMeta("sumMapIf", 2, 3, aggregate=True),
    "sumMapMerge": HogQLFunctionMeta("sumMapMerge", 1, 1, aggregate=True),
    "sumMapMergeIf": HogQLFunctionMeta("sumMapMergeIf", 2, 2, aggregate=True),
    "minMap": HogQLFunctionMeta("minMap", 1, 2, aggregate=True),
    "minMapIf": HogQLFunctionMeta("minMapIf", 2, 3, aggregate=True),
    "maxMap": HogQLFunctionMeta("maxMap", 1, 2, aggregate=True),
    "maxMapIf": HogQLFunctionMeta("maxMapIf", 2, 3, aggregate=True),
    "sumMerge": HogQLFunctionMeta("sumMerge", 1, 1, aggregate=True),
    "sumMergeIf": HogQLFunctionMeta("sumMergeIf", 2, 2, aggregate=True),
    "sumState": HogQLFunctionMeta("sumState", 1, 1, aggregate=True),
    "sumStateIf": HogQLFunctionMeta("sumStateIf", 2, 2, aggregate=True),
    "medianArray": HogQLFunctionMeta("medianArrayOrNull", 1, 1, aggregate=True),
    "skewSamp": HogQLFunctionMeta("skewSamp", 1, 1, aggregate=True),
    "skewSampIf": HogQLFunctionMeta("skewSampIf", 2, 2, aggregate=True),
    "skewPop": HogQLFunctionMeta("skewPop", 1, 1, aggregate=True),
    "skewPopIf": HogQLFunctionMeta("skewPopIf", 2, 2, aggregate=True),
    "kurtSamp": HogQLFunctionMeta("kurtSamp", 1, 1, aggregate=True),
    "kurtSampIf": HogQLFunctionMeta("kurtSampIf", 2, 2, aggregate=True),
    "kurtPop": HogQLFunctionMeta("kurtPop", 1, 1, aggregate=True),
    "kurtPopIf": HogQLFunctionMeta("kurtPopIf", 2, 2, aggregate=True),
    "uniq": HogQLFunctionMeta("uniq", 1, None, aggregate=True),
    "uniqIf": HogQLFunctionMeta("uniqIf", 2, None, aggregate=True),
    "uniqExact": HogQLFunctionMeta("uniqExact", 1, None, aggregate=True),
    "uniqExactState": HogQLFunctionMeta("uniqExactState", 1, None, aggregate=True),
    "uniqExactMerge": HogQLFunctionMeta("uniqExactMerge", 1, None, aggregate=True),
    "uniqExactIf": HogQLFunctionMeta("uniqExactIf", 2, None, aggregate=True),
    # "uniqCombined": HogQLFunctionMeta("uniqCombined", 1, 1, aggregate=True),
    # "uniqCombinedIf": HogQLFunctionMeta("uniqCombinedIf", 2, 2, aggregate=True),
    # "uniqCombined64": HogQLFunctionMeta("uniqCombined64", 1, 1, aggregate=True),
    # "uniqCombined64If": HogQLFunctionMeta("uniqCombined64If", 2, 2, aggregate=True),
    "uniqHLL12": HogQLFunctionMeta("uniqHLL12", 1, None, aggregate=True),
    "uniqHLL12If": HogQLFunctionMeta("uniqHLL12If", 2, None, aggregate=True),
    "uniqTheta": HogQLFunctionMeta("uniqTheta", 1, None, aggregate=True),
    "uniqThetaIf": HogQLFunctionMeta("uniqThetaIf", 2, None, aggregate=True),
    "uniqMerge": HogQLFunctionMeta("uniqMerge", 1, 1, aggregate=True),
    "uniqMergeIf": HogQLFunctionMeta("uniqMergeIf", 2, 2, aggregate=True),
    "uniqMap": HogQLFunctionMeta("uniqMap", 1, 1, aggregate=True),
    "uniqMapMerge": HogQLFunctionMeta("uniqMapMerge", 1, 1, aggregate=True),
    "uniqMapMergeIf": HogQLFunctionMeta("uniqMapMergeIf", 2, 2, aggregate=True),
    "uniqState": HogQLFunctionMeta("uniqState", 1, 1, aggregate=True),
    "uniqStateIf": HogQLFunctionMeta("uniqStateIf", 2, 2, aggregate=True),
    "uniqUpToMerge": HogQLFunctionMeta("uniqUpToMerge", 1, 1, 1, 1, aggregate=True),
    "median": HogQLFunctionMeta("median", 1, 1, aggregate=True),
    "medianIf": HogQLFunctionMeta("medianIf", 2, 2, aggregate=True),
    "medianExact": HogQLFunctionMeta("medianExact", 1, 1, aggregate=True),
    "medianExactIf": HogQLFunctionMeta("medianExactIf", 2, 2, aggregate=True),
    "medianExactLow": HogQLFunctionMeta("medianExactLow", 1, 1, aggregate=True),
    "medianExactLowIf": HogQLFunctionMeta("medianExactLowIf", 2, 2, aggregate=True),
    "medianExactHigh": HogQLFunctionMeta("medianExactHigh", 1, 1, aggregate=True),
    "medianExactHighIf": HogQLFunctionMeta("medianExactHighIf", 2, 2, aggregate=True),
    "medianExactWeighted": HogQLFunctionMeta("medianExactWeighted", 1, 1, aggregate=True),
    "medianExactWeightedIf": HogQLFunctionMeta("medianExactWeightedIf", 2, 2, aggregate=True),
    "medianTiming": HogQLFunctionMeta("medianTiming", 1, 1, aggregate=True),
    "medianTimingIf": HogQLFunctionMeta("medianTimingIf", 2, 2, aggregate=True),
    "medianTimingWeighted": HogQLFunctionMeta("medianTimingWeighted", 1, 1, aggregate=True),
    "medianTimingWeightedIf": HogQLFunctionMeta("medianTimingWeightedIf", 2, 2, aggregate=True),
    "medianDeterministic": HogQLFunctionMeta("medianDeterministic", 1, 1, aggregate=True),
    "medianDeterministicIf": HogQLFunctionMeta("medianDeterministicIf", 2, 2, aggregate=True),
    "medianTDigest": HogQLFunctionMeta("medianTDigest", 1, 1, aggregate=True),
    "medianTDigestIf": HogQLFunctionMeta("medianTDigestIf", 2, 2, aggregate=True),
    "medianTDigestWeighted": HogQLFunctionMeta("medianTDigestWeighted", 1, 1, aggregate=True),
    "medianTDigestWeightedIf": HogQLFunctionMeta("medianTDigestWeightedIf", 2, 2, aggregate=True),
    "medianBFloat16": HogQLFunctionMeta("medianBFloat16", 1, 1, aggregate=True),
    "medianBFloat16If": HogQLFunctionMeta("medianBFloat16If", 2, 2, aggregate=True),
    "quantile": HogQLFunctionMeta("quantile", 1, 1, min_params=1, max_params=1, aggregate=True),
    "quantileIf": HogQLFunctionMeta("quantileIf", 2, 2, min_params=1, max_params=1, aggregate=True),
    "quantiles": HogQLFunctionMeta("quantiles", 1, None, aggregate=True),
    "quantilesIf": HogQLFunctionMeta("quantilesIf", 2, 2, min_params=1, max_params=1, aggregate=True),
    # "quantileExact": HogQLFunctionMeta("quantileExact", 1, 1, aggregate=True),
    # "quantileExactIf": HogQLFunctionMeta("quantileExactIf", 2, 2, aggregate=True),
    # "quantileExactLow": HogQLFunctionMeta("quantileExactLow", 1, 1, aggregate=True),
    # "quantileExactLowIf": HogQLFunctionMeta("quantileExactLowIf", 2, 2, aggregate=True),
    # "quantileExactHigh": HogQLFunctionMeta("quantileExactHigh", 1, 1, aggregate=True),
    # "quantileExactHighIf": HogQLFunctionMeta("quantileExactHighIf", 2, 2, aggregate=True),
    # "quantileExactWeighted": HogQLFunctionMeta("quantileExactWeighted", 1, 1, aggregate=True),
    # "quantileExactWeightedIf": HogQLFunctionMeta("quantileExactWeightedIf", 2, 2, aggregate=True),
    # "quantileTiming": HogQLFunctionMeta("quantileTiming", 1, 1, aggregate=True),
    # "quantileTimingIf": HogQLFunctionMeta("quantileTimingIf", 2, 2, aggregate=True),
    # "quantileTimingWeighted": HogQLFunctionMeta("quantileTimingWeighted", 1, 1, aggregate=True),
    # "quantileTimingWeightedIf": HogQLFunctionMeta("quantileTimingWeightedIf", 2, 2, aggregate=True),
    # "quantileDeterministic": HogQLFunctionMeta("quantileDeterministic", 1, 1, aggregate=True),
    # "quantileDeterministicIf": HogQLFunctionMeta("quantileDeterministicIf", 2, 2, aggregate=True),
    # "quantileTDigest": HogQLFunctionMeta("quantileTDigest", 1, 1, aggregate=True),
    # "quantileTDigestIf": HogQLFunctionMeta("quantileTDigestIf", 2, 2, aggregate=True),
    # "quantileTDigestWeighted": HogQLFunctionMeta("quantileTDigestWeighted", 1, 1, aggregate=True),
    # "quantileTDigestWeightedIf": HogQLFunctionMeta("quantileTDigestWeightedIf", 2, 2, aggregate=True),
    # "quantileBFloat16": HogQLFunctionMeta("quantileBFloat16", 1, 1, aggregate=True),
    # "quantileBFloat16If": HogQLFunctionMeta("quantileBFloat16If", 2, 2, aggregate=True),
    # "quantileBFloat16Weighted": HogQLFunctionMeta("quantileBFloat16Weighted", 1, 1, aggregate=True),
    # "quantileBFloat16WeightedIf": HogQLFunctionMeta("quantileBFloat16WeightedIf", 2, 2, aggregate=True),
    "simpleLinearRegression": HogQLFunctionMeta("simpleLinearRegression", 2, 2, aggregate=True),
    "simpleLinearRegressionIf": HogQLFunctionMeta("simpleLinearRegressionIf", 3, 3, aggregate=True),
    # "stochasticLinearRegression": HogQLFunctionMeta("stochasticLinearRegression", 1, 1, aggregate=True),
    # "stochasticLinearRegressionIf": HogQLFunctionMeta("stochasticLinearRegressionIf", 2, 2, aggregate=True),
    # "stochasticLogisticRegression": HogQLFunctionMeta("stochasticLogisticRegression", 1, 1, aggregate=True),
    # "stochasticLogisticRegressionIf": HogQLFunctionMeta("stochasticLogisticRegressionIf", 2, 2, aggregate=True),
    # "categoricalInformationValue": HogQLFunctionMeta("categoricalInformationValue", 1, 1, aggregate=True),
    # "categoricalInformationValueIf": HogQLFunctionMeta("categoricalInformationValueIf", 2, 2, aggregate=True),
    "contingency": HogQLFunctionMeta("contingency", 2, 2, aggregate=True),
    "contingencyIf": HogQLFunctionMeta("contingencyIf", 3, 3, aggregate=True),
    "cramersV": HogQLFunctionMeta("cramersV", 2, 2, aggregate=True),
    "cramersVIf": HogQLFunctionMeta("cramersVIf", 3, 3, aggregate=True),
    "cramersVBiasCorrected": HogQLFunctionMeta("cramersVBiasCorrected", 2, 2, aggregate=True),
    "cramersVBiasCorrectedIf": HogQLFunctionMeta("cramersVBiasCorrectedIf", 3, 3, aggregate=True),
    "theilsU": HogQLFunctionMeta("theilsU", 2, 2, aggregate=True),
    "theilsUIf": HogQLFunctionMeta("theilsUIf", 3, 3, aggregate=True),
    "maxIntersections": HogQLFunctionMeta("maxIntersections", 2, 2, aggregate=True),
    "maxIntersectionsIf": HogQLFunctionMeta("maxIntersectionsIf", 3, 3, aggregate=True),
    "maxIntersectionsPosition": HogQLFunctionMeta("maxIntersectionsPosition", 2, 2, aggregate=True),
    "maxIntersectionsPositionIf": HogQLFunctionMeta("maxIntersectionsPositionIf", 3, 3, aggregate=True),
    "windowFunnel": HogQLFunctionMeta("windowFunnel", 1, 99, aggregate=True),
    "md5": HogQLFunctionMeta("hex(MD5({}))", 1, 1, aggregate=True, using_placeholder_arguments=True),
}
