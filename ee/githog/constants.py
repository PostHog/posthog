INCLUDE_WORKFLOW_FILE = False

IGNORE_PATTERNS = ["node_modules/*", "dist/*", ".git/*", ".github/*", "*.md", "LICENSE"]
INCLUDE_PATTERNS = ["package.json"]
CREATE_PATTERNS = [".env.example"]


PR_TITLE = "Integrate PostHog 🦔"
PR_BODY = """
This draft PR was automatically generated to help you integrate PostHog into your repository 🦔.

Here's what you need to do next to get things working:

{pr_instructions}

Note: GitHog is still an experimental project, and uses AI to generate PRs, so make sure to review the changes before merging!

Whilst you're waiting for CI to run, here's a poem for you to enjoy:

In a burrow, dimly lit,
Hedgehogs shipped their PostHog kit.
“Events will flow!” said Harold, proud,
“We'll track them all! We're data-bound!”
But Sally frowned, her quills on edge,
“This logs a Pageview… on every pledge?”

A merge conflict soon appeared,
A sight all hedgehogs truly feared.
“Rebase it quick!” said Larry, bold—
But Jenkins sighed, “Your tests? They're old.”
They shipped it live—“The graphs don't lie!”
And soon they cheered… as conversions soared sky-high.
"""
