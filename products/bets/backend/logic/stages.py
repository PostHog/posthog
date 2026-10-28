from ..facade.enums import BetStatus, WorkStage

ACTIVE = (WorkStage.WORKING, WorkStage.REVIEW, WorkStage.LIVE)
OPEN = (*ACTIVE, WorkStage.STUCK)
LIVE = (BetStatus.SETTING_UP, BetStatus.RUNNING)
