from collections import defaultdict

from django.db import migrations


def backfill_initial_history(apps, schema_editor):
    FeatureRequest = apps.get_model("customer_analytics", "FeatureRequest")
    FeatureRequestAccountLink = apps.get_model("customer_analytics", "FeatureRequestAccountLink")
    FeatureRequestHistory = apps.get_model("customer_analytics", "FeatureRequestHistory")
    FeatureRequestProductAreaLink = apps.get_model("customer_analytics", "FeatureRequestProductAreaLink")

    last_request_id = None
    while True:
        requests = FeatureRequest._base_manager.order_by("id")
        if last_request_id is not None:
            requests = requests.filter(id__gt=last_request_id)
        request_batch = list(requests[:1000])
        if not request_batch:
            break

        request_ids = [request.id for request in request_batch]
        existing_request_ids = set(
            FeatureRequestHistory._base_manager.filter(
                feature_request_id__in=request_ids,
                is_initial=True,
            ).values_list("feature_request_id", flat=True)
        )
        accounts_by_request_id = {
            account["feature_request_id"]: account
            for account in FeatureRequestAccountLink._base_manager.filter(feature_request_id__in=request_ids).values(
                "feature_request_id",
                "account_id",
                "account__name",
            )
        }
        product_areas_by_request_id = defaultdict(list)
        for product_area in (
            FeatureRequestProductAreaLink._base_manager.filter(feature_request_id__in=request_ids)
            .order_by("product_area__display_order", "product_area__name", "product_area_id")
            .values("feature_request_id", "product_area_id", "product_area__name")
        ):
            product_areas_by_request_id[product_area["feature_request_id"]].append(
                {
                    "id": str(product_area["product_area_id"]),
                    "name": product_area["product_area__name"],
                }
            )

        history_batch = []
        for request in request_batch:
            if request.id in existing_request_ids:
                continue
            account = accounts_by_request_id.get(request.id)
            history_batch.append(
                FeatureRequestHistory(
                    team_id=request.team_id,
                    feature_request_id=request.id,
                    changes=[
                        {"field": "status", "before": None, "after": request.status},
                        {
                            "field": "priority",
                            "before": None,
                            "after": request.priority,
                        },
                        {
                            "field": "account",
                            "before": None,
                            "after": (
                                {
                                    "id": str(account["account_id"]),
                                    "name": account["account__name"],
                                }
                                if account is not None
                                else None
                            ),
                        },
                        {
                            "field": "product_areas",
                            "before": [],
                            "after": product_areas_by_request_id[request.id],
                        },
                    ],
                    is_initial=True,
                    source="manual",
                    actor_id=request.created_by_id,
                    changed_at=request.created_at,
                )
            )
        FeatureRequestHistory._base_manager.bulk_create(history_batch, batch_size=1000, ignore_conflicts=True)
        last_request_id = request_batch[-1].id


class Migration(migrations.Migration):
    dependencies = [("customer_analytics", "0033_feature_request_lifecycle")]

    operations = [
        migrations.RunPython(backfill_initial_history, migrations.RunPython.noop),
    ]
