
from posthog.api.utils import action
from ee.githog.main import setup_posthog_pull_request
from ee.models.pull_request import PullRequest
from rest_framework import serializers
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin

class PullRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PullRequest
        fields = [
            'id',
            'team',
            'metadata',
            'status',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

class PullRequestViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = PullRequestSerializer
    permission_classes = [IsAuthenticated]
    queryset = PullRequest.objects.all()

    def safely_get_queryset(self):
        return PullRequest.objects.filter(team=self.team)

    @action(methods=['POST'], detail=False, url_path='setup')
    def setup(self, request, *args, **kwargs):
        """
        Create a new Pull Request by triggering the PostHog setup flow.
        
        This endpoint calls setup_posthog, which performs the actual integration logic
        (e.g. creating a PR in the user's repository) and returns a PullRequest instance.
        """
        # self.team is provided by the mixin
        if not self.team:
            return Response({"error": "No team associated with this user."}, status=status.HTTP_400_BAD_REQUEST)
        
        print("Creating pull request...")
        

        
        pull_request = PullRequest.objects.create(
            team=self.team,
            status=PullRequest.Status.PENDING,
            metadata={
                'repo_name': 'joshsny/nextjs-boilerplate'
            }
        )

        # setup_posthog_pull_request(pull_request.id)
        
        serializer = self.get_serializer(pull_request)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(methods=['POST'], detail=True, url_path='retry')
    def retry(self, request, pk=None):
        """
        Custom action to retry creating or updating a pull request.
        For demonstration, this simply updates the PR status.
        """
        pr = self.get_object()
        pr.status = "retrying"
        pr.save()
        serializer = self.get_serializer(pr)
        return Response(serializer.data, status=status.HTTP_200_OK)