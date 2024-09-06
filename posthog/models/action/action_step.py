from django.db import models


# DEPRECATED - this is now stored as JSON in the `steps_json` field of the Action model
class ActionStep(models.Model):
    CONTAINS = "contains"
    REGEX = "regex"
    EXACT = "exact"
    STRING_MATCHING = [(CONTAINS, CONTAINS), (REGEX, REGEX), (EXACT, EXACT)]

    action = models.ForeignKey("Action", related_name="action_steps", on_delete=models.CASCADE)
    text = models.CharField(max_length=400, null=True, blank=True)
    text_matching = models.CharField(
        # The implicit default is EXACT - no explicit default to avoid migration woes
        max_length=400,
        choices=STRING_MATCHING,
        null=True,
        blank=True,
    )
    href = models.CharField(max_length=65535, null=True, blank=True)
    href_matching = models.CharField(
        # The implicit default is EXACT - no explicit default to avoid migration woes
        max_length=400,
        choices=STRING_MATCHING,
        null=True,
        blank=True,
    )
    selector = models.CharField(max_length=65535, null=True, blank=True)
    url = models.CharField(max_length=65535, null=True, blank=True)
    url_matching = models.CharField(
        # This is from before text_matching and href_matching, which is why there's an explicit default of CONTAINS
        max_length=400,
        choices=STRING_MATCHING,
        default=CONTAINS,
        null=True,
        blank=True,
    )
    event = models.CharField(max_length=400, null=True, blank=True)
    properties = models.JSONField(default=list, null=True, blank=True)
    # DEPRECATED, DISUSED
    name = models.CharField(max_length=400, null=True, blank=True)
    # DEPRECATED, don't store new data here
    tag_name = models.CharField(max_length=400, null=True, blank=True)
