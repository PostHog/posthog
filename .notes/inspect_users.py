"""List users + their org memberships + accessible teams."""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()

from posthog.models import Organization, OrganizationMembership, Team, User

for u in User.objects.all().order_by("id"):
    memberships = OrganizationMembership.objects.filter(user=u)
    print(f"user {u.pk}: {u.email}  (is_staff={u.is_staff})")
    for m in memberships:
        teams = Team.objects.filter(organization=m.organization).order_by("id")
        team_list = ", ".join(f"{t.pk}={t.name!r}" for t in teams)
        print(f"  org {m.organization.pk}: {m.organization.name!r}  teams: {team_list}")
