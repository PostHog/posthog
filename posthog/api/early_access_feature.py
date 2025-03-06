from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from posthog.models import EarlyAccessFeature, Person, Cohort
from posthog.api.routing import StructuredViewSetMixin

class EarlyAccessFeatureViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    # ... existing viewset code ...

    @action(methods=['POST'], detail=True)
    def register(self, request, *args, **kwargs):
        early_access_feature = self.get_object()
        
        if not early_access_feature.cohort_id:
            return Response(
                {"error": "This feature does not have an associated waitlist cohort"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            person = Person.objects.get(
                persondistinct__team_id=self.team.id,
                persondistinct__distinct_id=request.user.distinct_id
            )
            
            cohort = Cohort.objects.get(id=early_access_feature.cohort_id, team_id=self.team.id)
            cohort.insert_users_by_list([person.uuid])

            return Response({"success": True}, status=status.HTTP_200_OK)
        except (Person.DoesNotExist, Cohort.DoesNotExist) as e:
            return Response(
                {"error": "Could not add user to waitlist"}, 
                status=status.HTTP_400_BAD_REQUEST
            ) 