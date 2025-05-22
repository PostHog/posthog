def convert_funnel_query(legacy_metric):
    # Extract and simplify series
    series = []
    for step in legacy_metric["funnels_query"]["series"]:
        step_copy = {}
        for key, value in step.items():
            if key != "name":  # Skip the name field
                step_copy[key] = value
        series.append(step_copy)

    new_metric = {"kind": "ExperimentMetric", "series": series, "metric_type": "funnel"}
    if name := legacy_metric.get("name"):
        new_metric["name"] = name

    return new_metric


def convert_trends_query(legacy_metric):
    source = legacy_metric["count_query"]["series"][0].copy()

    # Remove math_property_type if it exists
    if "math_property_type" in source:
        del source["math_property_type"]

    # Remove name if there's no math field
    if "math" not in source and "name" in source:
        del source["name"]

    new_metric = {"kind": "ExperimentMetric", "source": source, "metric_type": "mean"}

    if name := legacy_metric.get("name"):
        new_metric["name"] = name

    return new_metric


def convert_legacy_metric(metric):
    if metric.get("kind") == "ExperimentMetric":
        return metric  # Already new format
    if metric.get("kind") == "ExperimentFunnelsQuery":
        return convert_funnel_query(metric)
    if metric.get("kind") == "ExperimentTrendsQuery":
        return convert_trends_query(metric)
    raise ValueError(f"Unknown metric kind: {metric.get('kind')}")


def convert_legacy_metrics(metrics):
    return [convert_legacy_metric(m) for m in metrics]
