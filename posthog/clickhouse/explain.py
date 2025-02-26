import json

from posthog.schema import QueryIndexUsage


def find_all_reads(explain: dict) -> list[dict]:
    reads = []
    plan = explain.get("Plan", explain)
    if "Indexes" in plan:
        reads.append(plan)
    for subplan in plan.get("Plans", []):
        reads = reads + find_all_reads(subplan)
    return reads


def selected_less_granules(index, tiny_data_granules=100) -> bool:
    initial_granules = index.get("Initial Granules", 0)
    return index.get("Selected Granules", 0) < initial_granules or initial_granules < tiny_data_granules


def guestimate_index_use(plan_with_indexes: dict) -> dict:
    db_table = plan_with_indexes.get("Description", "")
    result = {
        "table": db_table,
    }
    if "Indexes" not in plan_with_indexes:
        result["use"] = QueryIndexUsage.NO
        return result

    indexes = plan_with_indexes.get("Indexes", [])

    if db_table.endswith(".person_distinct_id_overrides"):
        result["use"] = QueryIndexUsage.NO
        if len(indexes) == 1:
            index = indexes[0]
            if (
                index.get("Condition", "") != "true"
                and "team_id" in index.get("Keys", [])
                and selected_less_granules(index)
            ):
                result["use"] = QueryIndexUsage.YES

        return result
    elif db_table.endswith(".sharded_events"):
        result["use"] = QueryIndexUsage.NO
        minMax = False
        partition = False
        primary_key = False
        for index in indexes:
            if index.get("Condition", "") == "true":
                continue
            index_type = index.get("Type", "")
            if index_type == "MinMax":
                minMax = selected_less_granules(index)
            elif index_type == "Partition":
                partition = selected_less_granules(index)
            elif index_type == "PrimaryKey":
                primary_key = len(index.get("Keys", [])) > 1 and selected_less_granules(index)
        if (minMax or partition) and primary_key:
            result["use"] = QueryIndexUsage.YES

        return result

    result["use"] = QueryIndexUsage.UNDECISIVE
    minMax = False
    partition = False
    primary_key = False
    for index in indexes:
        if index.get("Condition", "") == "true":
            continue
        index_type = index.get("Type", "")
        if index_type == "MinMax":
            minMax = selected_less_granules(index)
        elif index_type == "Partition":
            partition = selected_less_granules(index)
        elif index_type == "PrimaryKey":
            primary_key = len(index.get("Keys", [])) > 1 and selected_less_granules(index)
    if (minMax or partition) and primary_key:
        result["use"] = QueryIndexUsage.YES

    return result


def extract_index_usage_from_plan(plan: str) -> QueryIndexUsage:
    try:
        explain = json.loads(plan)
        all_indices_use = [guestimate_index_use(r) for r in find_all_reads(explain[0])]
        if all(x["use"] == QueryIndexUsage.YES for x in all_indices_use):
            return QueryIndexUsage.YES
        elif any(x["use"] == QueryIndexUsage.YES for x in all_indices_use):
            return QueryIndexUsage.PARTIAL
        elif all(x["use"] == QueryIndexUsage.NO for x in all_indices_use):
            return QueryIndexUsage.NO
    except json.decoder.JSONDecodeError:
        pass

    return QueryIndexUsage.UNDECISIVE
