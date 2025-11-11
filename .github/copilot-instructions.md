# GitHub Copilot Workspace Instructions

When working on issues in this repository:

1. **Always include the issue URL** in your work:
   - Reference the issue in PR descriptions using: `Closes https://github.com/PostHog/posthog/issues/ISSUE_NUMBER`
   - This ensures proper tracking and automatic issue closure when the PR is merged

2. **Development guidelines**: Follow the consolidated development instructions in the root `AGENTS.md` file, which includes:
   - Commands for testing, linting, and building
   - ClickHouse migration patterns
   - Code style guidelines
   - Important rules for contributions

3. **Pull request format**: Use the PR template (`.github/pull_request_template.md`) and include:
   - Clear problem description linking to the issue
   - List of changes made
   - Testing approach
   - Screenshots for frontend changes

4. **Code quality**: Before finalizing changes:
   - Run appropriate linters and formatters
   - Ensure tests pass
   - Follow the repository's coding conventions
