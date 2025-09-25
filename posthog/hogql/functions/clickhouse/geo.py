from posthog.hogql.ast import ArrayType, FloatType, IntegerType, StringType, TupleType
from posthog.hogql.functions.core import HogQLFunctionMeta

GEO_FUNCTIONS: dict[str, HogQLFunctionMeta] = {
    "greatCircleDistance": HogQLFunctionMeta("greatCircleDistance", 4, 4),
    "geoDistance": HogQLFunctionMeta("geoDistance", 4, 4),
    "greatCircleAngle": HogQLFunctionMeta("greatCircleAngle", 4, 4),
    "pointInEllipses": HogQLFunctionMeta("pointInEllipses", 6, None),
    "pointInPolygon": HogQLFunctionMeta("pointInPolygon", 2, None),
    "geohashEncode": HogQLFunctionMeta("geohashEncode", 2, 3),
    "geohashDecode": HogQLFunctionMeta("geohashDecode", 1, 1),
    "geohashesInBox": HogQLFunctionMeta("geohashesInBox", 5, 5),
    "h3IsValid": HogQLFunctionMeta(
        "h3IsValid",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetResolution": HogQLFunctionMeta(
        "h3GetResolution",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetBaseCell": HogQLFunctionMeta(
        "h3GetBaseCell",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3EdgeAngle": HogQLFunctionMeta(
        "h3EdgeAngle",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3EdgeLengthM": HogQLFunctionMeta(
        "h3EdgeLengthM",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3EdgeLengthKm": HogQLFunctionMeta(
        "h3EdgeLengthKm",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "geoToH3": HogQLFunctionMeta(
        "geoToH3",
        3,
        3,
        signatures=[
            ((FloatType(), FloatType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3ToGeo": HogQLFunctionMeta(
        "h3ToGeo",
        1,
        1,
        signatures=[
            ((IntegerType(),), TupleType(item_types=[FloatType(), FloatType()])),
        ],
    ),
    "h3ToGeoBoundary": HogQLFunctionMeta(
        "h3ToGeoBoundary",
        1,
        1,
        signatures=[
            ((IntegerType(),), ArrayType(item_type=TupleType(item_types=[FloatType(), FloatType()]))),
        ],
    ),
    "h3kRing": HogQLFunctionMeta(
        "h3kRing",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3HexAreaM2": HogQLFunctionMeta(
        "h3HexAreaM2",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3HexAreaKm2": HogQLFunctionMeta(
        "h3HexAreaKm2",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3IndexesAreNeighbors": HogQLFunctionMeta(
        "h3IndexesAreNeighbors",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3ToChildren": HogQLFunctionMeta(
        "h3ToChildren",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3ToParent": HogQLFunctionMeta(
        "h3ToParent",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3ToString": HogQLFunctionMeta(
        "h3ToString",
        1,
        1,
        signatures=[
            ((IntegerType(),), StringType()),
        ],
    ),
    "stringToH3": HogQLFunctionMeta(
        "stringToH3",
        1,
        1,
        signatures=[
            ((StringType(),), IntegerType()),
        ],
    ),
    "h3IsResClassIII": HogQLFunctionMeta(
        "h3IsResClassIII",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3IsPentagon": HogQLFunctionMeta(
        "h3IsPentagon",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetFaces": HogQLFunctionMeta(
        "h3GetFaces",
        1,
        1,
        signatures=[
            ((IntegerType(),), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3CellAreaM2": HogQLFunctionMeta(
        "h3CellAreaM2",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3CellAreaRads2": HogQLFunctionMeta(
        "h3CellAreaRads2",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3ToCenterChild": HogQLFunctionMeta(
        "h3ToCenterChild",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3ExactEdgeLengthM": HogQLFunctionMeta(
        "h3ExactEdgeLengthM",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3ExactEdgeLengthKm": HogQLFunctionMeta(
        "h3ExactEdgeLengthKm",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3ExactEdgeLengthRads": HogQLFunctionMeta(
        "h3ExactEdgeLengthRads",
        1,
        1,
        signatures=[
            ((IntegerType(),), FloatType()),
        ],
    ),
    "h3NumHexagons": HogQLFunctionMeta(
        "h3NumHexagons",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3PointDistM": HogQLFunctionMeta(
        "h3PointDistM",
        4,
        4,
        signatures=[
            ((FloatType(), FloatType(), FloatType(), FloatType()), FloatType()),
        ],
    ),
    "h3PointDistKm": HogQLFunctionMeta(
        "h3PointDistKm",
        4,
        4,
        signatures=[
            ((FloatType(), FloatType(), FloatType(), FloatType()), FloatType()),
        ],
    ),
    "h3PointDistRads": HogQLFunctionMeta(
        "h3PointDistRads",
        4,
        4,
        signatures=[
            ((FloatType(), FloatType(), FloatType(), FloatType()), FloatType()),
        ],
    ),
    "h3GetRes0Indexes": HogQLFunctionMeta(
        "h3GetRes0Indexes",
        0,
        0,
        signatures=[
            ((), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3GetPentagonIndexes": HogQLFunctionMeta(
        "h3GetPentagonIndexes",
        1,
        1,
        signatures=[
            ((IntegerType(),), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3Line": HogQLFunctionMeta(
        "h3Line",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3Distance": HogQLFunctionMeta(
        "h3Distance",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3HexRing": HogQLFunctionMeta(
        "h3HexRing",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3GetUnidirectionalEdge": HogQLFunctionMeta(
        "h3GetUnidirectionalEdge",
        2,
        2,
        signatures=[
            ((IntegerType(), IntegerType()), IntegerType()),
        ],
    ),
    "h3UnidirectionalEdgeIsValid": HogQLFunctionMeta(
        "h3UnidirectionalEdgeIsValid",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetOriginIndexFromUnidirectionalEdge": HogQLFunctionMeta(
        "h3GetOriginIndexFromUnidirectionalEdge",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetDestinationIndexFromUnidirectionalEdge": HogQLFunctionMeta(
        "h3GetDestinationIndexFromUnidirectionalEdge",
        1,
        1,
        signatures=[
            ((IntegerType(),), IntegerType()),
        ],
    ),
    "h3GetIndexesFromUnidirectionalEdge": HogQLFunctionMeta(
        "h3GetIndexesFromUnidirectionalEdge",
        1,
        1,
        signatures=[
            ((IntegerType(),), TupleType(item_types=[IntegerType(), IntegerType()])),
        ],
    ),
    "h3GetUnidirectionalEdgesFromHexagon": HogQLFunctionMeta(
        "h3GetUnidirectionalEdgesFromHexagon",
        1,
        1,
        signatures=[
            ((IntegerType(),), ArrayType(item_type=IntegerType())),
        ],
    ),
    "h3GetUnidirectionalEdgeBoundary": HogQLFunctionMeta(
        "h3GetUnidirectionalEdgeBoundary",
        1,
        1,
        signatures=[
            ((IntegerType(),), ArrayType(item_type=TupleType(item_types=[FloatType(), FloatType()]))),
        ],
    ),
}
