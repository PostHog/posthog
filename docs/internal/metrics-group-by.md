# Metrics group by

The Group by dropdown lists attributes by series count, from highest to lowest.
Each item shows its series count on the right.
Hover over a count to show the "Number of series with this attribute" tooltip.
Attributes with the same count appear in alphabetical order.
Search keeps this order.

The count includes distinct series that report data in the selected time window, across the project.
It does not count repeated data points or limit the results to the selected metric.
The count includes both metric attributes and resource attributes.
An attribute that occurs in both scopes counts once per series.
The `service_name` item uses the same count and order as other attributes.

Users can still enter custom attribute keys. Custom keys have no count until the API returns them.
