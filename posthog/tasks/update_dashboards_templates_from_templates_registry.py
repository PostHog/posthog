from posthog.helpers.dashboard_templates import create_global_templates


def update_dashboards_templates_from_templates_registry() -> int:
    """
    download https://github.com/PostHog/templates-repository/archive/refs/heads/main.zip and unzip it
    each file in the dashboards directory is saved as a DashboardTemplate

    existing templates (keyed on name) are updated, new ones are created
    """
    import json
    import os
    import tempfile
    import zipfile
    from urllib.request import urlopen

    url = "https://github.com/PostHog/templates-repository/archive/refs/heads/main.zip"
    with urlopen(url) as github_repo:
        with tempfile.TemporaryFile() as f:
            f.write(github_repo.read())
            with tempfile.TemporaryDirectory() as tempDir:
                with zipfile.ZipFile(f) as zfile:
                    zfile.extractall(tempDir)

                    global_templates = []
                    for file in os.listdir(f"{tempDir}/templates-repository-main/dashboards"):
                        with open(f"{tempDir}/templates-repository-main/dashboards/{file}") as template_file:
                            global_templates.append(json.load(template_file))

                    create_global_templates(global_templates)

                    return len(global_templates)
