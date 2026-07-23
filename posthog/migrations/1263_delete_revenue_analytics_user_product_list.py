from django.db import migrations

BATCH_SIZE = 10_000

# Matches the `path` the Revenue analytics tree item had in frontend/src/products.json.
# The product was removed, so pinned sidebar entries pointing at it are dead.
REVENUE_ANALYTICS_PRODUCT_PATH = "Revenue analytics"


def delete_revenue_analytics_user_product_list(apps, schema_editor):
    UserProductList = apps.get_model("posthog", "UserProductList")

    while True:
        ids = list(
            UserProductList.objects.filter(product_path=REVENUE_ANALYTICS_PRODUCT_PATH).values_list("id", flat=True)[
                :BATCH_SIZE
            ]
        )
        if not ids:
            break

        UserProductList.objects.filter(id__in=ids).delete()


class Migration(migrations.Migration):
    # Each batch commits on its own so deleting a large backlog of pinned entries never runs
    # as one long transaction (which would bloat WAL and hold locks on a big table).
    atomic = False

    dependencies = [("posthog", "1262_organization_members_can_see_org_members")]

    operations = [
        migrations.RunPython(delete_revenue_analytics_user_product_list, migrations.RunPython.noop),
    ]
