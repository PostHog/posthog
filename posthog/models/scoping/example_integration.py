"""
Example of how to integrate TeamScopedManager with an existing model.

This file demonstrates how you would migrate a model from the current
RootTeamManager to the new TeamScopedManager for automatic IDOR protection.

MIGRATION STRATEGY:
1. Add the middleware to settings.py
2. Switch models one at a time from RootTeamManager to TeamScopedManager
3. Audit and update code that intentionally queries across teams to use .unscoped()
4. Run tests and fix any failures

EXAMPLE MIGRATION FOR FeatureFlag:

Before:
    class FeatureFlag(RootTeamMixin, models.Model):
        # Uses RootTeamManager from RootTeamMixin
        ...

After:
    from posthog.models.scoping.manager import BackwardsCompatibleTeamScopedManager

    class FeatureFlag(RootTeamMixin, models.Model):
        # Override the manager from RootTeamMixin
        objects = BackwardsCompatibleTeamScopedManager()
        ...

MIDDLEWARE SETUP (settings.py):

    MIDDLEWARE = [
        ...
        'posthog.models.scoping.middleware.TeamScopingMiddleware',
        ...
    ]

    Place it after AuthenticationMiddleware so request.user is available.

CODE CHANGES NEEDED:

1. Cross-team queries need .unscoped():

    Before:
        # Admin view showing all flags
        all_flags = FeatureFlag.objects.all()

    After:
        # Explicit that this is intentionally cross-team
        all_flags = FeatureFlag.objects.unscoped().all()

2. Background jobs need team_scope() context:

    Before:
        @celery_task
        def process_flag(flag_id):
            flag = FeatureFlag.objects.get(pk=flag_id)

    After:
        from posthog.models.scoping import team_scope

        @celery_task
        def process_flag(flag_id, team_id):
            with team_scope(team_id):
                flag = FeatureFlag.objects.get(pk=flag_id)

    Or use unscoped if the task doesn't have team context:

        @celery_task
        def process_flag(flag_id):
            flag = FeatureFlag.objects.unscoped().get(pk=flag_id)

3. Tests need to either set team context or use unscoped:

    Before:
        def test_something(self):
            flag = FeatureFlag.objects.get(pk=self.flag.id)

    After:
        def test_something(self):
            with team_scope(self.team.id):
                flag = FeatureFlag.objects.get(pk=self.flag.id)

    Or for tests that intentionally test cross-team behavior:

        def test_cross_team(self):
            flags = FeatureFlag.objects.unscoped().all()
"""

from typing import TYPE_CHECKING

from django.db import models

from posthog.models.scoping.manager import BackwardsCompatibleTeamScopedManager
from posthog.models.utils import RootTeamMixin

if TYPE_CHECKING:
    pass


class ExampleTeamScopedModel(RootTeamMixin, models.Model):
    """
    Example model demonstrating automatic team scoping.

    This model uses BackwardsCompatibleTeamScopedManager which:
    - Automatically filters by team_id when request context is set
    - Still supports explicit filter(team_id=X) for backwards compatibility
    - Provides .unscoped() for intentional cross-team queries
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    # Override the default manager from RootTeamMixin
    objects = BackwardsCompatibleTeamScopedManager()

    class Meta:
        # This is just an example - don't create the table
        abstract = True


# Example usage patterns:
"""
# In a view with authenticated user (middleware sets team context):
def my_view(request):
    # Automatically filtered to request.user.current_team_id
    items = ExampleTeamScopedModel.objects.all()

    # Still works - backwards compatible
    items = ExampleTeamScopedModel.objects.filter(team_id=some_team_id)

    # Intentional cross-team query
    all_items = ExampleTeamScopedModel.objects.unscoped().all()


# In a background job:
from posthog.models.scoping import team_scope

@celery_task
def process_items(team_id):
    with team_scope(team_id):
        # Filtered to specified team
        items = ExampleTeamScopedModel.objects.all()


# In tests:
class MyTest(TestCase):
    def test_something(self):
        with team_scope(self.team.id):
            item = ExampleTeamScopedModel.objects.get(pk=self.item.id)
"""
