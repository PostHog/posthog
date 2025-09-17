from urllib.parse import urlparse

from django.db import migrations

import structlog


# Populates the recording_domains field from domains of the app_urls
def backfill_recording_domains(apps, _):
    logger = structlog.get_logger(__name__)
    logger.info("starting 0258_team_recording_domains")
    Team = apps.get_model("posthog", "Team")

    all_teams = Team.objects.all().only("id", "app_urls", "recording_domains")
    num_teams_to_update = len(all_teams)
    batch_size = 500

    for i in range(0, num_teams_to_update, batch_size):
        logger.info(f"Updating permitted domains for team {i} to {i + batch_size}")
        teams_in_batch = all_teams[i : i + batch_size]

        for team in teams_in_batch:
            recording_domains: set[str] = set()
            for app_url in team.app_urls:
                # Extract just the domain from the URL
                parsed_url = urlparse(app_url)
                if parsed_url.netloc and parsed_url.scheme:
                    domain_of_app_url = parsed_url.scheme + "://" + parsed_url.netloc
                    recording_domains.add(domain_of_app_url)
                else:
                    # If the URL is invalid, just ignore it
                    logger.info(f"Could not parse invalid URL {app_url} for team {team.id}")
                    pass
            team.recording_domains = list(recording_domains)

        # Bulk update the teams in the DB
        Team.objects.bulk_update(teams_in_batch, ["recording_domains"])
        logger.info(f"Successful update of team {i} to {i + batch_size}")


# Because of the nature of this backfill, there's no way to reverse it without potentially destroying customer data
# However, we still need a reverse function, so that we can rollback other migrations
def reverse(apps, _):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0258_team_recording_domains"),
    ]

    operations = [
        migrations.RunPython(backfill_recording_domains, reverse, elidable=True),
    ]
