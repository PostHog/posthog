from ..core import HogQLFunctionMeta

# json
JSON_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "isValidJSON": HogQLFunctionMeta("isValidJSON", 1, 1),
    "JSONHas": HogQLFunctionMeta("JSONHas", 1, None),
    "JSONLength": HogQLFunctionMeta("JSONLength", 1, None),
    "JSONArrayLength": HogQLFunctionMeta("JSONArrayLength", 1, None),
    "JSONType": HogQLFunctionMeta("JSONType", 1, None),
    "JSONExtract": HogQLFunctionMeta("JSONExtract", 2, None),
    "JSONExtractUInt": HogQLFunctionMeta("JSONExtractUInt", 1, None),
    "JSONExtractInt": HogQLFunctionMeta("JSONExtractInt", 1, None),
    "JSONExtractFloat": HogQLFunctionMeta("JSONExtractFloat", 1, None),
    "JSONExtractBool": HogQLFunctionMeta("JSONExtractBool", 1, None),
    "JSONExtractString": HogQLFunctionMeta("JSONExtractString", 1, None),
    "JSONExtractKey": HogQLFunctionMeta("JSONExtractKey", 1, None),
    "JSONExtractKeys": HogQLFunctionMeta("JSONExtractKeys", 1, None),
    "JSONExtractRaw": HogQLFunctionMeta("JSONExtractRaw", 1, None),
    "JSONExtractArrayRaw": HogQLFunctionMeta("JSONExtractArrayRaw", 1, None),
    "JSONExtractKeysAndValues": HogQLFunctionMeta("JSONExtractKeysAndValues", 1, 3),
    "JSONExtractKeysAndValuesRaw": HogQLFunctionMeta("JSONExtractKeysAndValuesRaw", 1, None),
    "JSON_VALUE": HogQLFunctionMeta("JSON_VALUE", 2, None),
}
