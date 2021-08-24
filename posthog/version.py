VERSION = "1.27.0"

try:
    import git

    repo = git.Repo(search_parent_directories=True)
    GIT_SHA = repo.head.object.hexsha
except Exception:
    GIT_SHA = "Unavailable"
