from posthog.data_freshness import DataSourceSpec
from posthog.schema_enums import ProductKey

# Destination invocations, successful or not. A destination that is only erroring is still
# a project doing something.
DATA_SOURCES = [DataSourceSpec(product=ProductKey.PIPELINE_DESTINATIONS, app_metrics_source="hog_function")]
