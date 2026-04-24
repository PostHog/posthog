---
title: Linking GitHub as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Github
---

The GitHub connector can link issues, pull requests, commits, stargazers, and releases to PostHog.

To link GitHub:

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to GitHub.

3. Select your **Authentication type**. OAuth is the default and recommended method:
   - **OAuth (GitHub App)** – Click the GitHub account field and follow the prompts to connect your GitHub account. This handles authentication automatically.
   - **Personal access token (PAT)** – If you prefer using a PAT, select this option. Go to your [personal access tokens settings](https://github.com/settings/tokens) in GitHub, click **Generate new token**, give it a name, select the required scopes (`repo` for private repositories or `public_repo` for public repositories), and paste the token into PostHog.

4. Select the repository you want to sync:
   - **OAuth** – Use the searchable dropdown to find and select a repository your GitHub integration has access to.
   - **PAT** – Manually enter the repository in the format `owner/repo` (e.g., `posthog/posthog`).

   Click **Next**.

5. Set up the schemas you want to sync and modify the method and frequency as needed. Once done, click **Import**.

Once the syncs are complete, you can start using GitHub data in PostHog.
