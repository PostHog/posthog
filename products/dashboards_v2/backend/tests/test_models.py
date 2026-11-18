import pytest

from django.db import IntegrityError, transaction

from products.dashboards_v2.backend.models import DashboardV2


@pytest.mark.django_db
def test_uid_is_unique_per_team_until_the_dashboard_is_deleted(team) -> None:
    spec = {"uid": "checkout", "title": "Checkout", "layout": {"type": "grid", "items": []}, "panels": {}}
    first = DashboardV2.objects.create(team=team, uid="checkout", title="Checkout", spec=spec)

    with pytest.raises(IntegrityError), transaction.atomic():
        DashboardV2.objects.create(team=team, uid="checkout", title="Checkout", spec=spec)

    first.deleted = True
    first.save()
    DashboardV2.objects.create(team=team, uid="checkout", title="Checkout", spec=spec)

    assert DashboardV2.objects.filter(uid="checkout").count() == 2
