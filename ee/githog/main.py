import os
import sys
from celery import shared_task
from langgraph.graph.graph import RunnableConfig

from ..models.pull_request import PullRequest

from .auth import get_installation, get_installation_token
from .graph.main import create_graph
from .graph.state import AgentState


import os
import sys
import github
from langgraph.graph.graph import RunnableConfig

from .auth import get_installation_token
from .graph.main import create_graph
from .graph.state import AgentState
from .github_utils import list_repositories

def setup_posthog_pull_request(pull_request_id: str) -> None:
    print("Setting up PostHog pull request...", pull_request_id)
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    POSTHOG_API_KEY = os.environ.get("POSTHOG_API_KEY")
    GITHUB_APP_ID = os.getenv("GITHUB_APP_ID")
    GITHUB_APP_PRIVATE_KEY = os.getenv("GITHUB_APP_PRIVATE_KEY")

    if not (OPENAI_API_KEY and POSTHOG_API_KEY and GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY):
        print("Missing one or more required environment variables.")
        sys.exit(1)


    pull_request = PullRequest.objects.get(id=pull_request_id)

    if pull_request.status != PullRequest.Status.PENDING:
        print("Pull request is not pending. Exiting.")
        sys.exit(1)

    if pull_request.metadata is None:
        print("Pull request metadata is missing. Exiting.")
        sys.exit(1)

    repo_name = pull_request.team.github_installation_id

    if not repo_name:
        print("Repo name is missing. Exiting.")
        sys.exit(1)
    
        

    GITHUB_TOKEN = get_installation_token()

    gh = github.Github(GITHUB_TOKEN)

    # print("Fetching accessible repositories...\n")
    # installation = get_installation()
    # repos = list_repositories(installation)

    # if not repos:
    #     print("No repositories found. Please check permissions.")
    #     sys.exit(1)

    # # Display repositories and let user choose
    # print("Select a repository:")
    # for idx, repo_name in enumerate(repos, start=1):
    #     print(f"{idx}. {repo_name}")

    # selected_index = input("\nEnter the number of the repository to use: ")

    # try:
    #     selected_index = int(selected_index) - 1
    #     if selected_index < 0 or selected_index >= len(repos):
    #         raise ValueError
    #     REPO_NAME = repos[selected_index]
    # except ValueError:
    #     print("Invalid selection. Exiting.")
    #     sys.exit(1)

    print(f"\nSelected repository: {repo_name}")

    repo = gh.get_repo(repo_name)

    # Initialize agent state
    initial_state: AgentState = {
        "changes": [],
        "all_files": [],
        "relevant_files": [],
        "branch": None,
        "pr_url": None,
        "committed": False,
        "framework": None
    }

    config = RunnableConfig(configurable={"thread_id": "run-1"})

    graph = create_graph(repo)

    final_state = graph.invoke(initial_state, config)

    print("\nFinal State:")
    print(final_state)

    if "pr_url" in final_state:
        print("Pull Request URL:", final_state["pr_url"])
    else:
        print("No PR was created.")