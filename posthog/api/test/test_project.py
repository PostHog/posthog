from posthog.api.test.test_team import EnvironmentToProjectRewriteClient, team_api_test_factory


class TestProjectAPI(team_api_test_factory()):  # type: ignore
    """
    We inherit from TestTeamAPI, as previously /api/projects/ referred to the Team model, which used to mean "project".
    Now as Team means "environment" and Project is separate, we must ensure backward compatibility of /api/projects/.
    At the same time, this class is where we can continue adding `Project`-specific API tests.
    """

    client_class = EnvironmentToProjectRewriteClient
