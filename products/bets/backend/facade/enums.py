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


class BetPhase(LabeledStrEnum):
    SETTING_UP = "setting_up", "Setting up"
    CHECKING_MEASURE = "checking_measure", "Checking the measure"
    FINDING_IDEAS = "finding_ideas", "Finding ideas"
    CHECKING_IDEAS = "checking_ideas", "Checking ideas"
    CHOOSING = "choosing"
    BUILDING = "building"
    REVIEWING = "reviewing"
    TESTING = "testing"
    CONFIRMING_GOAL = "confirming_goal", "Confirming the goal"
    WAITING = "waiting"
    PAUSED = "paused"
    ENDED = "ended"


class BetActionKind(LabeledStrEnum):
    IDEAS = "ideas"
    EDIT = "edit"
    PULL_REQUEST = "pull_request", "Pull request"
    WORK = "work"
    BUDGET = "budget"
    SETTINGS = "settings"


class BetTile(LabeledStrEnum):
    TRACKING = "tracking"
    MEASURE = "measure"
    SCOUT = "scout"
    IDEA = "idea"
    EXPERIMENT = "experiment"
    PULL_REQUEST = "pull_request", "Pull request"
    PROBLEM = "problem"
    IDLE = "idle"
    PAUSED = "paused"
    REACHED = "reached"
    ENDED = "ended"


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
