from posthog.schema_migrations.base import SchemaMigration


class Migration(SchemaMigration):
    """Convert boolean 'showMean' field to a 'meanRetentionCalculation' field with 'simple'/'weighted' values."""

    targets = {"RetentionQuery": 1}

    def transform(self, query: dict) -> dict:
        if query["kind"] != "RetentionQuery":
            return query

        if query["retentionFilter"] is None:
            return query

        if "showMean" in query["retentionFilter"]:
            if "meanRetentionCalculation" in query["retentionFilter"]:
                del query["retentionFilter"]["showMean"]
            else:
                query["retentionFilter"]["meanRetentionCalculation"] = (
                    "simple" if query["retentionFilter"]["showMean"] else "none"
                )
                del query["retentionFilter"]["showMean"]

        return query
