from dagster import Definitions, load_assets_from_modules, ScheduleDefinition

from . import ch_examples, deletes, orm_examples
from .person_overrides import ClickhouseClusterResource, squash_person_overrides

all_assets = load_assets_from_modules([ch_examples, deletes, orm_examples])

# Schedule to run deletes at 10 PM on Saturdays
deletes_schedule = ScheduleDefinition(
    job=deletes,
    cron_schedule="0 22 * * 6",  # At 22:00 (10 PM) on Saturday
    execution_timezone="UTC",
    name="deletes_schedule",
)

defs = Definitions(
    assets=all_assets,
    jobs=[squash_person_overrides],
    schedules=[deletes_schedule],
    resources={
        "cluster": ClickhouseClusterResource.configure_at_launch(),
    },
)
