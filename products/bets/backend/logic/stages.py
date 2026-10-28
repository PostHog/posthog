from ..facade.enums import WorkStage

ACTIVE = (WorkStage.WORKING, WorkStage.REVIEW, WorkStage.LIVE)
OPEN = (*ACTIVE, WorkStage.STUCK)
