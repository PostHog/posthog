# The list of functions allowed in parametric functions, e.g. sum in "arrayReduce('sum', [1, 2, 3])"
HOGQL_PERMITTED_PARAMETRIC_FUNCTIONS: set[str] = {
    "count",
    "countMap",
    "countMapState",
    "sum",
    "sumMap",
    "sumMapState",
    "min",
    "minMap",
    "minMapState",
    "max",
    "maxMap",
    "maxMapState",
    "avg",
    "avgState",
    "avgMap",
    "avgMapState",
    "uniq",
    "uniqState",
    "uniqMap",
    "uniqMapState",
}

# Functions where the first argument needs to be DateTime and not DateTime64
FIRST_ARG_DATETIME_FUNCTIONS = (
    "tumble",
    "tumbleStart",
    "tumbleEnd",
    "hop",
    "hopStart",
    "hopEnd",
)
