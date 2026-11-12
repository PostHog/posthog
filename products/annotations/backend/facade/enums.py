"""Choice enums of the annotations contracts. No Django imports, and light enough for the model to import."""

from posthog.enums import LabeledStrEnum


class AnnotationScope(LabeledStrEnum):
    INSIGHT = "dashboard_item", "insight"
    DASHBOARD = "dashboard", "dashboard"
    PROJECT = "project", "project"
    ORGANIZATION = "organization", "organization"
    RECORDING = "recording", "recording"


class AnnotationCreationType(LabeledStrEnum):
    USER = "USR", "user"
    GITHUB = "GIT", "GitHub"


class ChangeKind(LabeledStrEnum):
    FEATURE_FLAG = "feature_flag", "Feature flag"
    EXPERIMENT = "experiment", "Experiment"
    RELEASE = "release", "Release"
    ANNOTATION = "annotation", "Annotation"
