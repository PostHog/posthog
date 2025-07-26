from django.db import models


class PersonPropertiesSizeViolation(models.Model):
    """
    Logs violations when Person.properties field exceeds size limits.
    Used for understanding the distribution of person properties sizes over a certain limit.
    """

    id = models.BigAutoField(primary_key=True)
    person_id = models.BigIntegerField(db_index=True, help_text="ID of the person with the size violation")
    properties_size_bytes = models.BigIntegerField(help_text="Size of the properties field in bytes")

    detected_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "posthog_person_properties_size_violation"
        indexes = [
            models.Index(fields=["person_id", "detected_at"]),
            models.Index(fields=["properties_size_bytes"]),
        ]
