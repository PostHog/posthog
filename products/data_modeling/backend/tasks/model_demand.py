from celery import shared_task

from products.data_modeling.backend.logic.demand import ModelDemand


@shared_task(ignore_result=True)
def flush_model_demand() -> None:
    ModelDemand.flush()
