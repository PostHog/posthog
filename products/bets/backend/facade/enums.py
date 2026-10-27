from posthog.enums import LabeledStrEnum


class BetsAccessLevel(LabeledStrEnum):
    VIEWER = "viewer"
    TRADER = "trader"
    MANAGER = "manager"


class BetStatus(LabeledStrEnum):
    SETTING_UP = "setting_up", "Setting up"
    RUNNING = "running"
    PAUSED = "paused"
    REACHED = "reached", "Goal reached"
    SPENT = "spent", "Budget used"
    CLOSED = "closed"


class BetStatusChange(LabeledStrEnum):
    RUNNING = "running", "Start or resume"
    PAUSED = "paused", "Pause"
    CLOSED = "closed", "Close"


class BetDirection(LabeledStrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"


class BetWorkAction(LabeledStrEnum):
    RETRY = "retry"
    DROP = "drop"
    BUILD = "build"
    DISMISS = "dismiss"
    EXTEND = "extend"


class BetActivityResource(LabeledStrEnum):
    NONE = "", ""
    TASK = "task"
    EXPERIMENT = "experiment"
    FLAG = "flag"
    INSIGHT = "insight"
    PULL_REQUEST = "pull_request", "Pull request"


class WorkKind(LabeledStrEnum):
    TRACKING = "tracking"
    IDEA = "idea"
    CLEANUP = "cleanup"


class WorkStage(LabeledStrEnum):
    PROPOSED = "proposed"
    DISMISSED = "dismissed"
    WORKING = "working"
    REVIEW = "review", "In review"
    LIVE = "live"
    DONE = "done"
    DROPPED = "dropped"
    STUCK = "stuck"


class IdeaSource(LabeledStrEnum):
    SCOUT = "scout"
    OWNER = "owner"


class IdeaAssessment(LabeledStrEnum):
    PENDING = "pending"
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported", "Not supported"


class EvidenceKind(LabeledStrEnum):
    REPLAY = "replay", "Session replay"
    INSIGHT = "insight"
    CHART = "chart"
    EXPERIMENT = "experiment"
    ERROR = "error"
    LINK = "link"


class IdeaOutcome(LabeledStrEnum):
    WON = "won"
    LOST = "lost"
    FLAT = "flat", "No clear effect"
    HARMED = "harmed", "Guardrail regression"
    DROPPED = "dropped"


class StepBilling(LabeledStrEnum):
    CREDITS = "credits", "PostHog credits"
    SUBSCRIPTION = "subscription", "ChatGPT plan"


class ModelStep(LabeledStrEnum):
    SCOUT = "scout"
    TRACKING = "tracking"
    IDEA = "idea"


class LedgerKind(LabeledStrEnum):
    ALLOCATE = "allocate"
    DEALLOCATE = "deallocate"
    RESERVE = "reserve"
    RELEASE = "release"
    SPEND = "spend"
