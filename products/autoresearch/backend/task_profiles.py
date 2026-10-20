from products.tasks.backend.facade.profiles import GithubResolution, TaskProfile

TRAINING = TaskProfile(
    key="autoresearch.training",
    origin_product="autoresearch",
    billing_product="background_agents",
    listed=False,
    inherit_user_defaults=False,
    personal_mcp=False,
    github_resolution=GithubResolution.WITH_REPOSITORY,
)

PROFILES = (TRAINING,)
