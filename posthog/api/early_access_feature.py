from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count
from posthog.models import Person
from django.contrib.postgres.fields.jsonb import KeyTransform


class EarlyAccessFeatureViewSet(viewsets.ModelViewSet):
    # ... existing viewset code ...

    @action(methods=["GET"], detail=False)
    def enrollment_counts(self, request):
        feature_enrollments = (
            Person.objects.filter(properties__has_key="$feature_enrollment")
            .annotate(enrollment_properties=KeyTransform("$feature_enrollment", "properties"))
            .values("enrollment_properties")
            .annotate(count=Count("id"))
        )

        return Response(
            {str(enrollment["enrollment_properties"]): enrollment["count"] for enrollment in feature_enrollments}
        )
