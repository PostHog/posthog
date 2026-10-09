# Test cases for github-installation-first-team.
# ruff: noqa


def first_candidate(payload):
    # ruleid: github-installation-first-team
    return installation_team_ids(payload)[0]


def first_candidate_through_variable(payload):
    team_ids = installation_team_ids(payload)
    if not team_ids:
        return None
    # ruleid: github-installation-first-team
    return Team.objects.filter(pk=team_ids[0]).first()


def first_candidate_through_next(payload):
    team_ids = installation_team_ids(payload)
    # ruleid: github-installation-first-team
    return next(iter(team_ids), None)


def resolve_through_helper(payload):
    # ruleid: github-installation-first-team
    return _resolve_external_team(payload)


def first_integration(installation_id):
    # ruleid: github-installation-first-team
    return Integration.objects.filter(kind="github", integration_id=installation_id).order_by("id").first()


def first_integration_through_using(installation_id):
    # ruleid: github-installation-first-team
    return Integration.objects.using("default").filter(kind="github", integration_id=installation_id).first()


def first_integration_installation_before_kind(installation_id):
    # ruleid: github-installation-first-team
    return Integration.objects.filter(integration_id=installation_id, kind=Integration.IntegrationKind.GITHUB).first()


def first_slack_integration(slack_team_id):
    # ok: github-installation-first-team
    return Integration.objects.filter(kind="slack", integration_id=slack_team_id).first()


def indexed_integration(installation_id):
    # ruleid: github-installation-first-team
    return Integration.objects.filter(kind="github", integration_id=installation_id)[0]


def get_integration(installation_id):
    # ruleid: github-installation-first-team
    return Integration.objects.get(kind="github", integration_id=installation_id)


def every_candidate(payload):
    # ok: github-installation-first-team
    for team_id in installation_team_ids(payload):
        notify(team_id)


def candidate_set(payload, team_id):
    # ok: github-installation-first-team
    team_ids = set(installation_team_ids(payload))
    return team_id in team_ids


def candidate_membership(payload, team_id):
    # ok: github-installation-first-team
    return team_id in installation_team_ids(payload)


def team_scoped_integration(team_id, installation_id):
    # ok: github-installation-first-team
    return Integration.objects.filter(team_id=team_id, integration_id=installation_id).first()


def team_scoped_integration_get(team, installation_id):
    # ok: github-installation-first-team
    return Integration.objects.get(team=team, kind="github", integration_id=installation_id)


def team_scoped_integration_chained(team_id, installation_id):
    # ok: github-installation-first-team
    return Integration.objects.filter(team_id=team_id).filter(kind="github", integration_id=installation_id).first()


def team_scoped_helper(team_id, installation_id):
    # ok: github-installation-first-team
    return Integration.objects.first_github_for_team_installation(team_id, installation_id)


def every_integration(installation_id):
    # ok: github-installation-first-team
    return list(Integration.objects.filter(kind="github", integration_id=installation_id).order_by("team_id"))


def justified_exception(installation_id):
    # nosemgrep: github-installation-first-team -- the installation has one project by construction here
    return Integration.objects.filter(kind="github", integration_id=installation_id).first()
