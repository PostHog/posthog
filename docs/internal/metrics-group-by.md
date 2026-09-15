# Metrics group by

The Group by dropdown lists attributes by distinct value count, from highest to lowest.
Each item shows its distinct value count on the right.
Hover over a count to show the "Number of distinct values" tooltip.
Attributes with the same count appear in alphabetical order.
Search keeps this order.

The count uses attribute values from series whose latest metadata timestamp is at or after the selected start time.
It does not read raw metric samples or enforce the selected end time.
Counts are informational and most useful for recent series.
Metadata updates can lag samples, so this is not an exact count for the selected time window.
When a metric is selected, it only lists attributes from that metric.
When no metric is selected, it lists attributes from all metrics in the project.
The count includes both metric attributes and resource attributes.
Repeated values count once, even when many series have the same value.
For an attribute in both scopes, the nonempty resource value takes priority, as it does in chart grouping.
Otherwise, the count uses the metric attribute value. An empty string counts as one value.
The `service_name` item counts distinct service names, not series.

Users can still enter custom attribute keys. Custom keys have no count until the API returns them.
