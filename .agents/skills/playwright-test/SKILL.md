---
name: playwright-test
description: Write a playwright test, make sure it runs, and is not flaky.
allowed-tools: Bash, Read, Edit, Write, Glob, Grep, Agent, mcp__playwright__*
---

## Rules

- Don't use any locators with css selectors, prefer getting elements via accessibility roles or data-testids, add data-attr if required.
- Write fewer longer tests that do multiple things, split up by test.steps into logical steps
- Use page object models for common tasks and accessing common elements
- After UI interactions, always assert on UI changes, do not assert on network requests resolving
- Never put an if statement in a test

## Instructions

You are to plan an end to end playwright test for a feature.

### Step 1: Plan the test(s) to be done.

Use the Playwright MCP tools (e.g., `mcp__playwright__browser_navigate`, `mcp__playwright__browser_click`, `mcp__playwright__browser_screenshot`) to interact with the browser and plan your tests.

After your exploration, present the plan to me for confirmation or any changes.

### Step 2: Implement the test plan

- Write the tests, making sure to use common patterns used in neighbouring files.
- Run the tests with `BASE_URL='http://localhost:8010' pnpm --filter=@posthog/playwright exec playwright test <file name> --retries 0 --workers 3`
- Debug any failures. Look at screen shots, if needed launch the playwright mcp skills to interact with the browser. Go back to step 1 after attempting a fix.
- **Keep looping until all tests pass.** Do not give up or ask the user for help. You must resolve every failure yourself.

### Step 3: Ensure no flaky tests

After all tests pass in the file, run with `--repeat-each 10` added to the command. This will surface any flaky tests.

If any test fails across the 10 runs, treat it as a real failure: go back to Step 2, debug, fix, and re-run Step 3. Do not proceed to Step 4 until every run of every test passes.

### Step 4: Report

Once all tests pass, output a single line: **Testing Complete**
