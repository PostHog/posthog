"""
Constants for feature flag model and events.
"""


class CreationContext:
    FEATURE_FLAGS = "feature_flags"
    EXPERIMENTS = "experiments"
    SURVEYS = "surveys"
    EARLY_ACCESS_FEATURES = "early_access_features"
    WEB_EXPERIMENTS = "web_experiments"

    CHOICES = (
        FEATURE_FLAGS,
        EXPERIMENTS,
        SURVEYS,
        EARLY_ACCESS_FEATURES,
        WEB_EXPERIMENTS,
    )
