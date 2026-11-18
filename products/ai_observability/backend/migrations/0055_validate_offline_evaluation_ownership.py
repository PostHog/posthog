from django.db import migrations

from posthog.migration_helpers import ValidateForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0054_offline_evaluation_ownership_constraints"),
    ]

    operations = [
        ValidateForeignKey(model_name="offlineevaluationresult", name="aio_offline_result_scorer_owner_fk"),
        ValidateForeignKey(model_name="offlineevaluationresult", name="aio_offline_result_scorer_version_fk"),
        ValidateForeignKey(model_name="offlineexperiment", name="aio_offline_exp_dataset_owner_fk"),
        ValidateForeignKey(model_name="offlineexperimentitem", name="aio_offline_item_dataset_owner_fk"),
        ValidateForeignKey(model_name="offlineexperimentitem", name="aio_offline_item_experiment_fk"),
        ValidateForeignKey(model_name="offlineevaluationresult", name="aio_offline_result_item_fk"),
        ValidateForeignKey(model_name="offlineexperimentitempayload", name="aio_offline_item_payload_fk"),
        ValidateForeignKey(model_name="offlineevaluationresultpayload", name="aio_offline_result_payload_fk"),
    ]
