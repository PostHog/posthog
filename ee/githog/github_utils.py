from github import GithubException, Repository, Installation

def get_all_file_paths_in_repo(repo: Repository.Repository, branch="main") -> list[str]:
    try:
        tree = repo.get_git_tree(branch, recursive=True)
        return [element.path for element in tree.tree if element.type == "blob"]
    except GithubException as e:
        print(f"Error retrieving git tree: {e}")
        exit(1)

def create_pull_request(repo: Repository.Repository, branch: str, title: str, body: str) -> str:
    pr = repo.create_pull(title=title, body=body, head=branch, base="main")
    return pr.html_url

def request_review(repo: Repository.Repository, pr, reviewer: str):
    try:
        pr.create_review_request(reviewers=[reviewer])
    except GithubException as e:
        print(f"Error requesting review: {e}")

def list_repositories(installation: Installation.Installation) -> list[str]:
    """Lists all repositories the installation has access to."""

    repos = installation.get_repos()
    return [repo.full_name for repo in repos]