from typing import List, cast

from django.core.management.base import BaseCommand

from posthog.models import FeatureFlag, Team, User


class Command(BaseCommand):
    help = "Add and enable all feature flags in frontend/src/lib/constants.tsx for all teams"

    def handle(self, *args, **options):
        flags: List[str] = []
        with open("frontend/src/lib/constants.tsx") as f:
            lines = f.readlines()
            parsing_flags = False
            for line in lines:
                if parsing_flags:
                    if "}" in line:
                        parsing_flags = False
                    else:
                        try:
                            flag = line.split("'")[1]
                            flags.append(flag)
                        except IndexError:
                            pass

                elif "export const FEATURE_FLAGS" in line:
                    parsing_flags = True

        first_user = cast(User, User.objects.first())
        for team in Team.objects.all():
            existing_flags = FeatureFlag.objects.filter(team=team).values_list("key", flat=True)
            deleted_flags = FeatureFlag.objects.filter(team=team, deleted=True).values_list("key", flat=True)
            for flag in flags:
                if flag in deleted_flags:
                    ff = FeatureFlag.objects.filter(team=team, key=flag)[0]
                    ff.deleted = False
                    ff.save()
                    print(f"Undeleted feature flag '{flag} for team {team.id} {' - ' + team.name if team.name else ''}")
                elif flag not in existing_flags:
                    FeatureFlag.objects.create(
                        team=team, rollout_percentage=100, name=flag, key=flag, created_by=first_user
                    )
                    print(f"Created feature flag '{flag} for team {team.id} {' - ' + team.name if team.name else ''}")
