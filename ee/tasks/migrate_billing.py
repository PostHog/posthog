from typing import Dict, Optional

import requests

from ee.api.billing import build_billing_token
from ee.models import License
from ee.settings import BILLING_SERVICE_URL


def migrate_billing(
    events_price_map: Dict[str, str],
    recordings_price_id: str,
    dry_run: bool = False,
    limit: int = 10,
    organization_id: Optional[int] = None,
    ignore_ids: list = [],
) -> int:
    try:
        import stripe
        from multi_tenancy.models import OrganizationBilling  # noqa: F401
        from multi_tenancy.stripe import _init_stripe  # noqa: F401
    except ImportError:
        print("Couldn't import multi_tenancy models")  # noqa T201
        return 0
    license = License.objects.first_valid()
    if not license:  # mypy
        return 0
    _init_stripe()

    migrated_orgs = 0
    try:
        if organization_id:
            query = OrganizationBilling.objects.filter(organization_id=organization_id)
        else:
            query = OrganizationBilling.objects.exclude(stripe_customer_id__isnull=True).exclude(
                stripe_customer_id__exact=""
            )[:limit]
        for billing in query:
            if str(billing.organization.id) in ignore_ids:
                print("Ignoring: ", billing.organization.name)  # noqa T201
                continue
            try:
                should_delete = False
                print("Migrating billing for: ", billing.organization.name)  # noqa T201

                billing_service_token = build_billing_token(license, billing.organization)

                payload = {"stripe_customer_id_v1": billing.stripe_customer_id}
                if not billing.stripe_subscription_id:
                    should_delete = True
                elif billing.stripe_subscription_id:
                    subscription = stripe.Subscription.retrieve(billing.stripe_subscription_id)
                    if subscription["status"] == "active":
                        payload["stripe_subscription_id_v1"] = billing.stripe_subscription_id

                        items = subscription["items"]["data"]
                        if len(items) > 1:
                            # there should be only one item on old subscriptions
                            raise Exception("More than one item on subscription")

                        new_price_id = None
                        sub_item = items[0]
                        old_price_id = sub_item["price"]["id"]
                        if old_price_id in events_price_map:
                            new_price_id = events_price_map[old_price_id]

                        if new_price_id:
                            if dry_run:
                                print("Would have switched to new price", new_price_id)  # noqa T201
                                print(  # noqa T201
                                    "Would have created new item with free recordings", recordings_price_id
                                )
                            else:
                                print("Switching to new events price")  # noqa T201
                                # we switch the old event price id to the new one
                                stripe.SubscriptionItem.modify(
                                    sub_item["id"],
                                    price=new_price_id,
                                )
                                print("Creating new item with free recordings")  # noqa T201
                                # we create a new item with free session recordings
                                stripe.SubscriptionItem.create(
                                    subscription=billing.stripe_subscription_id,
                                    price=recordings_price_id,
                                )  # noqa T201
                                should_delete = True
                        else:
                            # we don't delete this org_billing yet as we don't have a matching price
                            print("No matching price found for", billing.organization.name)  # noqa T201
                            should_delete = False
                    else:
                        print("Subscription not active for", billing.organization.name)  # noqa T201
                        should_delete = True

                if not dry_run:
                    res = requests.patch(
                        f"{BILLING_SERVICE_URL}/api/billing",
                        headers={"Authorization": f"Bearer {billing_service_token}"},
                        json=payload,
                    )

                    if res.status_code != 200:
                        raise Exception(res.json())

                if dry_run:
                    print("Dry run, not deleting billing v1 for", billing.organization.name)  # noqa T201
                elif should_delete:
                    # we have done everything with this org, so we can delete it
                    print("Deleting billing v1 for", billing.organization.name)  # noqa T201
                    billing.delete()
                    migrated_orgs += 1

            except Exception as e:
                raise Exception(
                    {
                        "org_id": billing.organization.id,
                        "org_name": billing.organization.name,
                        "error": e,
                    }
                )
    except Exception as e:
        print("Error migrating billing", e)  # noqa T201

    return migrated_orgs
