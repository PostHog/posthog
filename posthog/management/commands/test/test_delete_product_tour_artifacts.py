from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey


class TestDeleteProductTourArtifacts(BaseTest):
    def test_deletes_tour_artifacts_and_keeps_customer_objects(self) -> None:
        targeting_flag = FeatureFlag.objects.create(
            team=self.team, key="product-tour-targeting-a", created_by=self.user
        )
        linked_flag = FeatureFlag.objects.create(team=self.team, key="customer-flag", created_by=self.user)
        tour_survey_flag = FeatureFlag.objects.create(team=self.team, key="survey-targeting-a", created_by=self.user)
        tour_survey = Survey.objects.create(
            team=self.team, name="Tour step survey", type="api", internal_targeting_flag=tour_survey_flag
        )
        other_survey = Survey.objects.create(team=self.team, name="Customer survey", type="popover")
        tour = ProductTour.objects.create(
            team=self.team, name="t", internal_targeting_flag=targeting_flag, linked_flag=linked_flag
        )
        tour.linked_surveys.add(tour_survey)

        call_command("delete_product_tour_artifacts", stdout=StringIO())
        assert FeatureFlag.objects.filter(id=targeting_flag.id, deleted=False).exists()
        assert Survey.objects.filter(id=tour_survey.id).exists()

        for _ in range(2):
            call_command("delete_product_tour_artifacts", "--live", stdout=StringIO())

        targeting_flag.refresh_from_db()
        assert targeting_flag.deleted and not targeting_flag.active
        assert not Survey.objects.filter(id=tour_survey.id).exists()
        assert not FeatureFlag.objects.filter(id=tour_survey_flag.id).exists()
        linked_flag.refresh_from_db()
        assert not linked_flag.deleted
        assert Survey.objects.filter(id=other_survey.id).exists()
